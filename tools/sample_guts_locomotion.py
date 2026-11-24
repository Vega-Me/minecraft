"""Offline, fail-closed subset of Molang; no eval/exec or external dependencies."""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'texture-packs/previews/guts-locomotion'
CLIPS = tuple('animation.guts_locomotion.' + x for x in ('arms', 'legs', 'torso'))


def evaluate(value, env):
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip().rstrip(';')
    # Only the exported simple conditional form is accepted; branches recurse.
    if '?' in text:
        condition, branches = text.split('?', 1)
        yes, no = branches.split(':', 1)
        return evaluate(yes if evaluate(condition, env) else no, env)
    tree = ast.parse(text, mode='eval')
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return float(n.value)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            return float(env[n.value.id + '.' + n.attr])
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return visit(n.operand) * (-1 if isinstance(n.op, ast.USub) else 1)
        if isinstance(n, ast.BinOp):
            a, b = visit(n.left), visit(n.right)
            if isinstance(n.op, ast.Add): return a + b
            if isinstance(n.op, ast.Sub): return a - b
            if isinstance(n.op, ast.Mult): return a * b
            if isinstance(n.op, ast.Div): return a / b
            if isinstance(n.op, ast.Mod): return a % b
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'math' and not n.keywords:
            functions = {'sin': lambda x: math.sin(math.radians(x)),
                         'cos': lambda x: math.cos(math.radians(x)),
                         'mod': lambda a, b: a % b,
                         'clamp': lambda x, a, b: max(a, min(b, x)), 'abs': abs}
            if n.func.attr in functions:
                return functions[n.func.attr](*(visit(a) for a in n.args))
        raise ValueError('Unsupported Molang syntax: ' + ast.dump(n))
    result = visit(tree.body)
    if not math.isfinite(result): raise ValueError('Nonfinite expression: ' + text)
    return result


def channel(value, time, env):
    if isinstance(value, dict):
        keys = sorted((float(k), v) for k, v in value.items())
        def vector(v, side):
            if isinstance(v, dict):
                if v.get('lerp_mode', 'linear') != 'linear':
                    raise ValueError('Only linear timeline interpolation is supported')
                v = v.get(side, v.get('post', v.get('pre')))
            return channel(v, time, env)
        if time <= keys[0][0]: return vector(keys[0][1], 'pre')
        for (a, av), (b, bv) in zip(keys, keys[1:]):
            if time <= b:
                left, right = vector(av, 'post'), vector(bv, 'pre')
                f = (time-a)/(b-a)
                return [x+(y-x)*f for x, y in zip(left, right)]
        return vector(keys[-1][1], 'post')
    if not isinstance(value, list): value = [value]*3
    if len(value) != 3: raise ValueError('Expected three-axis channel')
    return [evaluate(x, env) for x in value]


def pose(clips, elapsed, weight, sprint, rate, frame=1, fps=60):
    clock = (elapsed*rate) % .6667
    env = {'variable.guts_locomotion_clock': clock,
           'variable.guts_locomotion_active': 1,
           'variable.guts_locomotion_weight': weight,
           'query.modified_move_speed': weight,
           'query.is_sprinting': int(sprint), 'query.delta_time': 1/fps}
    bones, sources = {}, {}
    for name in CLIPS:
        clip = clips[name]
        time = evaluate(clip['anim_time_update'], env)
        if clip.get('loop'): time %= float(clip['animation_length'])
        env['query.anim_time'] = time
        blend = evaluate(clip.get('blend_weight', 1), env)
        sources[name] = {'anim_time': time, 'weight': blend}
        for bone, channels in clip['bones'].items():
            target = bones.setdefault(bone, {'rotation': [0.0]*3, 'position': [0.0]*3})
            for key in ('rotation', 'position'):
                values = channel(channels.get(key, [0, 0, 0]), time, env)
                target[key] = [a+b*blend for a, b in zip(target[key], values)]
    return {'frame': frame, 'elapsed': elapsed, 'shared_clock': clock, 'clips': sources, 'bones': bones}


def sample(root=ROOT, fps=60, seconds=2.0):
    path = Path(root) / 'texture-packs/Guts/animations/guts_locomotion.animation.json'
    raw = path.read_bytes()
    clips = json.loads(raw)['animations']
    result = {'fps': fps, 'seconds': seconds, 'source': str(path.relative_to(root)),
              'sha256': hashlib.sha256(raw).hexdigest(), 'clips': list(CLIPS),
              'notes': 'Steady-state ported clips only; linear timelines, no controller transitions or vanilla overlays. Not exact Minecraft engine equivalence.', 'modes': {}}
    for mode, weight, sprint, rate in [('WALK', .45, False, 1.0), ('SPRINT', .8, True, 1.18)]:
        frames = []
        for index in range(round(seconds*fps)+1):
            elapsed = index/fps
            frames.append(pose(clips, elapsed, weight, sprint, rate, index+1, fps))
        result['modes'][mode] = {'speed_weight': weight, 'sprinting': sprint, 'clock_rate': rate, 'samples': frames}
    def finite(v):
        if isinstance(v, float) and not math.isfinite(v): raise ValueError('Nonfinite sample')
        if isinstance(v, dict):
            for x in v.values(): finite(x)
        if isinstance(v, list):
            for x in v: finite(x)
    finite(result)
    result['finite_values_verified'] = True
    return result


def export(root=ROOT, output=OUT, seconds=2.0):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for fps in (30, 60):
        data = sample(root, fps, seconds)
        path = output / ('samples_%dfps.json' % fps)
        path.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')
        print(path)
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--seconds', type=float, default=2.0)
    args = parser.parse_args()
    if args.seconds <= 0: parser.error('--seconds must be positive')
    export(args.root, args.output, args.seconds)
