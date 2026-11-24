"""Create the narrow Actions & Stuff locomotion experiment from a supplied donor.

The donor is an input, not vendored. Run from anywhere:
  python3 tools/build_guts_locomotion.py /path/to/extracted/donor
Only the three vanilla locomotion aliases are routed; vanilla root stays intact.
"""
import argparse
import copy
import json
import pathlib
import uuid
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / 'texture-packs/Guts'
NAMESPACE = 'guts_locomotion'


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def build(donor):
    source = json.loads((donor / 'animations/player_basic.animation.json').read_text())
    motion = source['animations']['animation.actor.move']
    player_path = PACK / 'entity/player.entity.json'
    entity = json.loads(player_path.read_text())
    player = entity['minecraft:client_entity']['description']
    scripts = player['scripts']
    # Disjoint from all existing variables. Conditions deliberately restrict scope.
    checks = [
        '!variable.is_first_person', '!variable.is_paperdoll',
        '!variable.map_face_icon', '!query.is_spectator', 'query.is_alive',
        'query.is_on_ground', '!query.is_sneaking', '!query.is_swimming',
        '!query.is_gliding', '!query.is_crawling', '!query.is_riding',
        'variable.swim_amount <= 0.0', '!query.item_is_charged',
        '!query.is_sleeping', '!query.is_emoting', '!query.blocking',
        '!query.is_charging', 'query.main_hand_item_use_duration <= 0.0',
        'variable.attack_time <= 0.0', 'query.modified_move_speed > 0.01',
    ]
    scripts['initialize'] = [s for s in scripts['initialize'] if 'variable.guts_locomotion_' not in s]
    scripts['initialize'] += ['variable.guts_locomotion_clock = 0.0;']
    scripts['pre_animation'] = [s for s in scripts['pre_animation'] if 'variable.guts_locomotion_' not in s]
    scripts['pre_animation'] += [
        'variable.guts_locomotion_active = ' + ' && '.join(checks) + ';',
        'variable.guts_locomotion_weight = math.clamp(query.modified_move_speed, 0.0, 1.0);',
        'variable.guts_locomotion_clock = variable.guts_locomotion_active ? '
        'math.mod(variable.guts_locomotion_clock + query.delta_time * '
        '(query.is_sprinting ? 1.18 : 1.0), 0.6667) : 0.0;',
    ]
    controllers = {}
    animations = {}
    # Preserve aliases referenced by the base game; route each to vanilla or donor.
    for alias, group, vanilla in [
        ('move.arms', 'arms', 'animation.player.move.arms'),
        ('move.legs', 'legs', 'animation.player.move.legs'),
        ('bob', 'torso', 'animation.player.bob'),
    ]:
        prefix = 'guts_locomotion_' + group
        ctrl = 'controller.animation.guts_locomotion.' + group
        anim = 'animation.guts_locomotion.' + group
        player['animations'][alias] = ctrl
        player['animations'][prefix + '_vanilla'] = vanilla
        player['animations'][prefix + '_ported'] = anim
        controllers[ctrl] = {
            'initial_state': 'vanilla',
            'states': {
                'vanilla': {
                    'animations': [prefix + '_vanilla'],
                    'blend_transition': 0.12,
                    'transitions': [{'ported': 'variable.guts_locomotion_active'}],
                },
                'ported': {
                    'animations': [prefix + '_ported'],
                    'blend_transition': 0.12,
                    'transitions': [{'vanilla': '!variable.guts_locomotion_active'}],
                },
            },
        }
        keep = {'arms': ['leftArm', 'rightArm'], 'legs': ['leftLeg', 'rightLeg'],
                'torso': ['waist', 'body']}[group]
        clip = {
            'loop': True,
            'animation_length': motion['animation_length'],
            'anim_time_update': 'variable.guts_locomotion_clock',
            'blend_weight': 'variable.guts_locomotion_active ? variable.guts_locomotion_weight : 0.0',
            'bones': {b: copy.deepcopy(motion['bones'][b]) for b in keep},
        }
        # Source sprint lean ends at +5deg waist, +1 Z and +/-15deg arm roll.
        # Use the steady-state pose only: no stop, jump or particle dependencies.
        if group == 'torso':
            clip['bones']['waist']['rotation'][0] = '5 + 5 * query.is_sprinting'
            clip['bones']['waist']['position'] = [0, 0, 'query.is_sprinting']
        if group == 'arms':
            for side, sign in [('leftArm', -1), ('rightArm', 1)]:
                bone = clip['bones'][side]
                bone['rotation'][1] = bone['rotation'][1] + f' + {-sign * 10} * query.is_sprinting'
                bone['rotation'][2] = f'{sign * 15} * query.is_sprinting'
                bone['position'][1] = bone['position'][1] + ' + query.is_sprinting'
        animations[anim] = clip
    write(player_path, entity)
    write(PACK / 'animation_controllers/guts_locomotion.animation_controllers.json',
          {'format_version': '1.10.0', 'animation_controllers': controllers})
    write(PACK / 'animations/guts_locomotion.animation.json',
          {'format_version': '1.8.0', 'animations': animations})
    # Stable test identity permits side-by-side install; never reuse Guts UUIDs.
    manifest_path = PACK / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['header']['name'] = 'Guts - Locomotion Test'
    manifest['header']['description'] = 'Guts (based on Soulless | packsmc.com). Walking/sprinting test adapted from Actions & Stuff 1.0.2.'
    manifest['header']['uuid'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/Vega-Me/minecraft/guts-locomotion/header'))
    manifest['header']['version'] = [1, 0, 1]
    manifest['modules'][0]['uuid'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/Vega-Me/minecraft/guts-locomotion/module'))
    manifest['modules'][0]['version'] = [1, 0, 1]
    write(manifest_path, manifest)
    archive = ROOT / 'texture-packs/dist/Guts_Locomotion_Test.mcpack'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(PACK.rglob('*')):
            if path.is_file() and path.name != '.DS_Store':
                z.write(path, path.relative_to(PACK))
    print(archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('donor', type=pathlib.Path)
    build(parser.parse_args().donor)
