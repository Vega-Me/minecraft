#!/usr/bin/env python3
"""Offline structural/gate checks only; does not certify Minecraft engine behavior."""
import ast
import copy
import hashlib
import json
import pathlib
import re
import subprocess
import uuid
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / 'texture-packs/Guts'
REPORT = ROOT / 'texture-packs/previews/guts-locomotion/static-verification.json'
BASE = 'fe8113c78ac1ba12157ab81d70088d434fbb8621'


def pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError('Duplicate JSON key: ' + key)
        out[key] = value
    return out


def loads(raw):
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def evaluate(source, values):
    """Parse restricted expressions into validated Python AST; never use eval."""
    source = source.strip().rstrip(';')
    # Only the simple top-level conditional form is accepted.
    if '?' in source:
        condition, rest = source.split('?', 1)
        yes, no = rest.split(':', 1)
        # Validate/evaluate both branches, including the branch not selected.
        a, b, c = evaluate(condition, values), evaluate(yes, values), evaluate(no, values)
        return b if a else c
    source = source.replace('&&', ' and ').replace('||', ' or ')
    source = re.sub(r'!(?!=)', ' not ', source).strip()
    tree = ast.parse(source, mode='eval')
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
               ast.USub, ast.Constant, ast.Attribute, ast.Name, ast.Load,
               ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
               ast.Call)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError('Unsupported expression node: ' + type(node).__name__)
        if isinstance(node, ast.Call) and (ast.unparse(node.func) != 'math.clamp' or len(node.args) != 3 or node.keywords):
            raise ValueError('Only math.clamp(x, low, high) is allowed')
        if isinstance(node, ast.Attribute) and (not isinstance(node.value, ast.Name) or node.value.id not in ('query', 'variable', 'math')):
            raise ValueError('Unsupported attribute')
    def visit(n):
        if isinstance(n, ast.Expression): return visit(n.body)
        if isinstance(n, ast.Constant):
            if type(n.value) not in (bool, int, float): raise ValueError('Non-numeric constant')
            return n.value
        if isinstance(n, ast.Attribute): return values[ast.unparse(n)]
        if isinstance(n, ast.UnaryOp): return not visit(n.operand) if isinstance(n.op, ast.Not) else -visit(n.operand)
        if isinstance(n, ast.BoolOp):
            results = [bool(visit(v)) for v in n.values]
            return all(results) if isinstance(n.op, ast.And) else any(results)
        if isinstance(n, ast.Call):
            x, low, high = [visit(v) for v in n.args]
            return min(max(x, low), high)
        if isinstance(n, ast.Compare):
            left = visit(n.left)
            result = True
            for op, other in zip(n.ops, n.comparators):
                right = visit(other)
                result &= {ast.Lt: lambda: left < right, ast.LtE: lambda: left <= right,
                           ast.Gt: lambda: left > right, ast.GtE: lambda: left >= right,
                           ast.Eq: lambda: left == right, ast.NotEq: lambda: left != right}[type(op)]()
                left = right
            return result
        raise ValueError('Unsupported expression')
    return visit(tree)


def main():
    checks = []
    def check(name, fn):
        try:
            details = fn()
            checks.append(dict(name=name, passed=True, details=details))
        except Exception as exc:
            checks.append(dict(name=name, passed=False, error=str(exc)))
    def require(ok, message):
        if not ok: raise AssertionError(message)
    data = {}
    def json_check():
        paths = [PACK / 'entity/player.entity.json', PACK / 'manifest.json',
                 PACK / 'animations/guts_locomotion.animation.json',
                 PACK / 'animation_controllers/guts_locomotion.animation_controllers.json']
        for path in paths: data[path.name] = loads(path.read_text())
        return [str(p.relative_to(ROOT)) for p in paths]
    check('JSON syntax and duplicate keys', json_check)
    def aliases():
        desc = data['player.entity.json']['minecraft:client_entity']['description']
        clips = data['guts_locomotion.animation.json']['animations']
        controllers = data['guts_locomotion.animation_controllers.json']['animation_controllers']
        expected_clips = {'animation.guts_locomotion.' + x for x in ('arms', 'legs', 'torso')}
        require(set(clips) == expected_clips, 'Expected exactly three custom clips')
        require(set(controllers) == {'controller.animation.guts_locomotion.' + x for x in ('arms','legs','torso')}, 'Unexpected controllers')
        definitions = {}
        for folder, key in [('animations','animations'), ('animation_controllers','animation_controllers')]:
            for path in (PACK / folder).rglob('*.json'):
                for ident in loads(path.read_text()).get(key, {}):
                    require(ident not in definitions, 'Duplicate ID: ' + ident)
                    definitions[ident] = str(path)
        mapping = desc['animations']
        reached = set()
        for route, group, vanilla in [('move.arms','arms','animation.player.move.arms'), ('move.legs','legs','animation.player.move.legs'), ('bob','torso','animation.player.bob')]:
            cid = 'controller.animation.guts_locomotion.' + group
            require(mapping[route] == cid, 'Incorrect entry alias: ' + route)
            require(mapping['guts_locomotion_'+group+'_vanilla'] == vanilla, 'Incorrect vanilla fallback')
            require(mapping['guts_locomotion_'+group+'_ported'] == 'animation.guts_locomotion.'+group, 'Incorrect custom alias')
            def walk(ident, stack):
                require(ident not in stack, 'Recursive route: ' + ident)
                if ident in clips: reached.add(ident); return
                if ident == vanilla: return
                require(ident in controllers, 'Unresolved or unexpected route: ' + ident)
                ctrl = controllers[ident]
                require(ctrl['initial_state'] in ctrl['states'], 'Invalid initial state')
                for state in ctrl['states'].values():
                    for transition in state.get('transitions', []):
                        require(set(transition) <= set(ctrl['states']), 'Unknown transition target')
                    for entry in state.get('animations', []):
                        names = [entry] if isinstance(entry,str) else entry.keys()
                        for alias in names:
                            require(alias in mapping, 'Unknown alias: ' + alias)
                            walk(mapping[alias], stack + [ident])
            walk(cid, [])
        require(reached == expected_clips, 'Not all three clips reachable')
        forbidden = {'particle_effects','sound_effects','timeline','on_entry','on_exit'}
        def scan(obj):
            if isinstance(obj, dict):
                require(not forbidden.intersection(obj), 'Effect/event provider present')
                for value in obj.values(): scan(value)
            elif isinstance(obj,list):
                for value in obj: scan(value)
        scan(clips); scan(controllers)
        return {'reachable_clips':sorted(reached), 'unique_definition_count':len(definitions)}
    check('Aliases, unique IDs, restricted routes and no effects', aliases)
    def gates():
        desc = data['player.entity.json']['minecraft:client_entity']['description']
        statements = desc['scripts']['pre_animation']
        def assignment(name):
            matches = [s.split('=',1)[1].strip().rstrip(';') for s in statements if re.match(r'^\s*'+re.escape(name)+r'\s*=',s)]
            require(len(matches)==1, 'Expected one assignment: '+name)
            return matches[0]
        gate = assignment('variable.guts_locomotion_active')
        weight = assignment('variable.guts_locomotion_weight')
        baseline = {key:0 for key in re.findall(r'(?:query|variable)\.[A-Za-z_]+', gate+' '+weight)}
        baseline.update({'query.is_alive':1,'query.is_on_ground':1,'query.modified_move_speed':0.2,'query.is_sprinting':0})
        exclusions = {'first_person':('variable.is_first_person',1),'paperdoll':('variable.is_paperdoll',1),'map':('variable.map_face_icon',1),'dead':('query.is_alive',0),'spectator':('query.is_spectator',1),'airborne':('query.is_on_ground',0),'sneak':('query.is_sneaking',1),'swim':('query.is_swimming',1),'swimfade':('variable.swim_amount',0.01),'glide':('query.is_gliding',1),'crawl':('query.is_crawling',1),'riding':('query.is_riding',1),'sleep':('query.is_sleeping',1),'emote':('query.is_emoting',1),'attack':('variable.attack_time',0.01),'blocking':('query.blocking',1),'using':('query.main_hand_item_use_duration',0.01),'charging':('query.is_charging',1),'charged_crossbow':('query.item_is_charged',1),'stationary':('query.modified_move_speed',0)}
        results = []
        for sprint in (0,1):
            for name, override in [('walking' if not sprint else 'sprinting',None)] + list(exclusions.items()):
                env = dict(baseline, **{'query.is_sprinting':sprint})
                if override: env[override[0]] = override[1]
                active = bool(evaluate(gate,env))
                require(active == (override is None), 'Gate failed: '+name)
                env['variable.guts_locomotion_weight'] = evaluate(weight,env)
                blends = {}
                # Evaluate current-frame gate while an outgoing controller still retains clip weight.
                env['variable.guts_locomotion_active'] = int(active)
                for ident, clip in data['guts_locomotion.animation.json']['animations'].items():
                    blend = evaluate(clip['blend_weight'],env)
                    require(blend == 0 if override else blend > 0, 'Hard blend gate failed: '+name+' '+ident)
                    blends[ident] = blend
                results.append(dict(sprinting=bool(sprint),case=name,active=active,blend_weights=blends))
        return {'gate':gate,'cases':results,'outgoing_clip_retained_current_frame_gate':True}
    check('Gate truth table and outgoing hard blend exclusions', gates)
    def rig_and_samples():
        from sample_guts_locomotion import sample, channel
        rig = loads((REPORT.parent / 'vanilla-humanoid.geo.json').read_text())['minecraft:geometry'][0]
        rig_bones = {b['name'] for b in rig['bones']}
        clips = data['guts_locomotion.animation.json']['animations']
        animated = set()
        channels_owned = set()
        loop_delta = 0.0
        for clip in clips.values():
            require(clip['anim_time_update'] == 'variable.guts_locomotion_clock', 'Unsynchronized animation clock')
            for bone, channels in clip['bones'].items():
                require(bone in rig_bones, 'Unknown reference bone: '+bone)
                animated.add(bone)
                for kind, values in channels.items():
                    require((bone,kind) not in channels_owned, 'Channel owned twice')
                    channels_owned.add((bone,kind))
                    a = channel(values, 0, {'query.anim_time':0, 'query.is_sprinting':1})
                    end = clip['animation_length']
                    b = channel(values, end, {'query.anim_time':end, 'query.is_sprinting':1})
                    loop_delta = max(loop_delta, *(abs(x-y) for x,y in zip(a,b)))
        require(animated == {'leftArm','rightArm','leftLeg','rightLeg','waist','body'}, 'Unexpected animated bones')
        require(loop_delta < .1, 'Large loop discontinuity: '+str(loop_delta))
        thirty, sixty = sample(ROOT,30), sample(ROOT,60)
        for mode in ('WALK','SPRINT'):
            for a,b in zip(thirty['modes'][mode]['samples'], sixty['modes'][mode]['samples'][::2]):
                require(a['bones']==b['bones'], 'Framerate-dependent sampled pose')
                require(all(abs(c['anim_time']-a['shared_clock'])<1e-9 for c in a['clips'].values()), 'Clip phase mismatch')
        return {'animated_bones':sorted(animated),'finite_samples':364,
                'fps_compared':[30,60],'max_loop_channel_delta':loop_delta,
                'clip_sha256':sixty['sha256'], 'engine_equivalence':False}
    check('Reference bones, finite sampled motion, shared phase and loop continuity', rig_and_samples)
    def preserved_player():
        original = loads(subprocess.check_output(['git','-C',str(ROOT),'show',BASE+':texture-packs/Guts/entity/player.entity.json']))
        restored = copy.deepcopy(data['player.entity.json'])
        desc = restored['minecraft:client_entity']['description']
        original_desc = original['minecraft:client_entity']['description']
        for key in ('initialize','pre_animation'):
            desc['scripts'][key] = [s for s in desc['scripts'][key] if 'variable.guts_locomotion_' not in s]
        for alias in list(desc['animations']):
            if alias.startswith('guts_locomotion_'): del desc['animations'][alias]
        for alias in ('move.arms','move.legs','bob'):
            desc['animations'][alias] = original_desc['animations'][alias]
        require(restored == original, 'Existing player configuration changed outside approved injections')
        return 'All original scripts, first-person/combat aliases, skin/render bindings and back-sword logic preserved.'
    check('Existing player behavior retained outside three routes and new variables', preserved_player)
    def protected():
        def git(*args): return subprocess.check_output(['git','-C',str(ROOT),*args])
        allowed = {'entity/player.entity.json','manifest.json'}
        tracked = git('ls-tree','-r','--name-only',BASE,'texture-packs/Guts').decode().splitlines()
        count = 0
        for rel in tracked:
            local = rel.removeprefix('texture-packs/Guts/')
            if local in allowed: continue
            require((ROOT/rel).read_bytes() == git('show',BASE+':'+rel), 'Protected tracked file changed: '+rel)
            count += 1
        changed = git('diff',BASE,'--name-only','--','texture-packs/Guts').decode().splitlines()
        allowed_changes = allowed | {'animations/guts_locomotion.animation.json', 'animation_controllers/guts_locomotion.animation_controllers.json'}
        require(all(p.removeprefix('texture-packs/Guts/') in allowed_changes for p in changed), 'Unexpected source changes')
        archive_rel = 'texture-packs/dist/Guts.mcpack'
        require((ROOT/archive_rel).read_bytes() == git('show',BASE+':'+archive_rel), 'Original archive changed')
        with zipfile.ZipFile(ROOT/archive_rel) as archive:
            original = loads(archive.read('manifest.json'))
        base = loads(git('show',BASE+':texture-packs/Guts/manifest.json'))
        current = data['manifest.json']
        def ids(manifest): return [manifest['header']['uuid']] + [m['uuid'] for m in manifest['modules']]
        test_ids = ids(current)
        for value in test_ids: uuid.UUID(value)
        require(len(set(test_ids)) == len(test_ids), 'Repeated test UUID')
        require(not set(test_ids).intersection(ids(base)+ids(original)), 'Test UUID overlaps base/archive')
        return {'unchanged_tracked_assets':count,'base_commit':BASE,'archived_root_manifest_checked':True,'test_uuids':test_ids}
    check('Protected files, original baseline and archived manifest UUIDs', protected)
    def package():
        path = ROOT / 'texture-packs/dist/Guts_Locomotion_Test.mcpack'
        expected = {str(p.relative_to(PACK)):p for p in PACK.rglob('*') if p.is_file() and p.name != '.DS_Store'}
        with zipfile.ZipFile(path) as archive:
            require(archive.testzip() is None, 'Corrupt archive')
            require(set(archive.namelist()) == set(expected), 'Unexpected archive contents')
            for name,p in expected.items():
                require(archive.read(name) == p.read_bytes(), 'Stale packaged file: '+name)
        return {'file_count':len(expected), 'root_manifest':True,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    check('Installable archive matches all source files', package)
    report = {'scope':'Offline static verification only; no real engine tests performed or certified.', 'passed':all(c['passed'] for c in checks),'checks':checks}
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,indent=2)+'\n')
    for item in checks: print(('PASS ' if item['passed'] else 'FAIL ')+item['name']+(': '+item['error'] if not item['passed'] else ''))
    print('Report:',REPORT)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
