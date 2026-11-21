#!/usr/bin/env python3
"""Read-only worktree inventory and recorded verification evidence."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
from radio_verification import validate_report

ENV = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'}


def git(path, *args, check=True):
    result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(path), *args], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise ValueError(result.stderr.decode('utf-8', 'replace').strip() or 'git failed')
    return result


def decoded(data):
    return data.decode('utf-8', 'surrogateescape')


def textgit(path, *args):
    return decoded(git(path, *args).stdout).strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def valid_path(value):
    return isinstance(value, str) and bool(value) and not PurePosixPath(value).is_absolute() and all(p not in ('..', '.git') for p in PurePosixPath(value).parts)


def registry(path):
    try:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('integration_branch'), str) or not data['integration_branch'] or data['integration_branch'].startswith('-'):
            raise ValueError('expected version 1 and integration_branch')
        for group in ('targets', 'shared_fixes', 'checks'):
            if not isinstance(data.get(group), list) or any(not isinstance(x, dict) for x in data[group]):
                raise ValueError(f'{group} must be a list of objects')
        for group, key in [('targets', 'name'), ('shared_fixes', 'id'), ('checks', 'id')]:
            ids = [x.get(key) for x in data[group]]
            if any(not isinstance(x, str) or not x or '/' in x or x in ('.', '..') for x in ids) or len(set(ids)) != len(ids):
                raise ValueError(f'invalid or duplicate {group} {key}')
        names = {x['name'] for x in data['targets']}
        checks = {x['id'] for x in data['checks']}
        for t in data['targets']:
            if not isinstance(t.get('branch'), str) or not t['branch'] or t['branch'].startswith('-') or not isinstance(t.get('checks'), list) or any(c not in checks for c in t['checks']):
                raise ValueError(f'invalid target {t["name"]}')
        for c in data['checks']:
            if not c.get('inputs'):
                raise ValueError(f"empty inputs in check {c['id']}")
            if any(not isinstance(c.get(k), list) or any(not valid_path(p) for p in c[k]) for k in ('inputs', 'reports')):
                raise ValueError(f'invalid paths in check {c["id"]}')
            scoped = c.get('inputs_by_target', {})
            if not isinstance(scoped, dict) or any(name not in names or not isinstance(paths, list) or any(not valid_path(p) for p in paths) for name, paths in scoped.items()):
                raise ValueError(f'invalid target inputs in check {c["id"]}')
        for f in data['shared_fixes']:
            if not isinstance(f.get('commit'), str) or not re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', f['commit']) or not isinstance(f.get('targets'), list) or any(t not in names for t in f['targets']) or not isinstance(f.get('paths'), list) or any(not valid_path(p) for p in f['paths']):
                raise ValueError(f'invalid shared fix {f["id"]}')
        return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f'invalid registry: {exc}') from exc


def worktrees(repo):
    raw = git(repo, 'worktree', 'list', '--porcelain', '-z').stdout
    result = []
    for record in raw.split(b'\0\0'):
        if not record:
            continue
        item = {}
        for field in record.split(b'\0'):
            key, _, value = decoded(field).partition(' ')
            item[key] = value if value else True
        result.append(item)
    return result


def observation(path):
    head = textgit(path, 'rev-parse', '--verify', 'HEAD')
    raw = git(path, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignore-submodules=none').stdout
    fields = raw.split(b'\0')
    changes = []
    i = 0
    while i < len(fields) and fields[i]:
        entry = decoded(fields[i]); i += 1
        change = {'status': entry[:2], 'path': entry[3:]}
        if 'R' in entry[:2] or 'C' in entry[:2]:
            change['original_path'] = decoded(fields[i]); i += 1
        changes.append(change)
    return head, changes


def changed_paths(changes):
    return {v for c in changes for k, v in c.items() if k in ('path', 'original_path')}


def manifest(root, inputs, report_paths):
    entries, errors = {}, []
    root = Path(root)
    excluded = PurePosixPath('build/worktree-status')
    def visit(rel):
        rel = PurePosixPath(rel)
        if '.git' in rel.parts or rel == excluded or excluded in rel.parents or str(rel) in report_paths:
            return
        path = root.joinpath(*rel.parts)
        try:
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                entries[str(rel)] = {'path': str(rel), 'type': 'symlink', 'mode': mode, 'target': os.readlink(path)}
                errors.append(f'{rel}: symlink input is not followed')
            elif stat.S_ISDIR(info.st_mode):
                entries[str(rel)] = {'path': str(rel), 'type': 'directory', 'mode': mode}
                for child in sorted(path.iterdir(), key=lambda p: p.name):
                    visit(rel / child.name)
            elif stat.S_ISREG(info.st_mode):
                entries[str(rel)] = {'path': str(rel), 'type': 'file', 'mode': mode, 'sha256': digest(path.read_bytes())}
            else:
                errors.append(f'{rel}: unsupported file type')
        except FileNotFoundError:
            entries[str(rel)] = {'path': str(rel), 'type': 'missing'}
            errors.append(f'{rel}: missing')
        except OSError as exc:
            errors.append(f'{rel}: {exc.strerror}')
    for value in sorted(set(inputs)):
        parts = PurePosixPath(value).parts
        rel = PurePosixPath(value)
        if rel == excluded or excluded in rel.parents or value in report_paths:
            errors.append(f'{value}: an evidence output cannot be a source input')
        elif any((root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts))):
            errors.append(f'{value}: symlink in parent path')
        else:
            visit(value)
    return [entries[k] for k in sorted(entries)], sorted(errors)


def snapshot(path, target, checks):
    head, changes = observation(path)
    branch = textgit(path, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    definitions = [c for c in checks if c['id'] in target['checks']]
    inputs = sorted({p for c in definitions for p in [*c['inputs'], *c.get('inputs_by_target', {}).get(target['name'], [])]})
    reports = {p for c in definitions for p in c['reports']}
    items, errors = manifest(path, inputs, reports)
    items_after, errors_after = manifest(path, inputs, reports)
    head_after, changes_after = observation(path)
    branch_after = textgit(path, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    unstable = (head, changes, branch, items, errors) != (head_after, changes_after, branch_after, items_after, errors_after)
    if branch != target['branch']:
        errors.append(f"checked-out branch {branch} does not match {target['branch']}")
    result = {'version': 1, 'target': target['name'], 'branch': target['branch'], 'head': head, 'dirty': bool(changes), 'checks_digest': digest(canonical(definitions)), 'inputs': inputs, 'manifest': items, 'complete': not errors and not unstable, 'errors': errors, 'unstable': unstable}
    if 'radio_verification' in target:
        result['radio_verification'] = target['radio_verification']
    result['fingerprint'] = digest(canonical(result))
    return result


def path_hash(root, obj):
    if not isinstance(obj, dict) or not valid_path(obj.get('path')) or not isinstance(obj.get('sha256'), str) or len(obj['sha256']) != 64:
        raise ValueError('invalid artifact or report')
    path = Path(root) / obj['path']
    try:
        if not path.is_file() or not path.resolve().is_relative_to(Path(root).resolve()):
            return False
        return digest(path.read_bytes()) == obj['sha256']
    except OSError:
        return False


def run_evidence(data, path, target, check, checks, snap_cache, result):
    if data.get('target') != target['name'] or data.get('check') != check['id'] or data.get('result') not in ('running', 'pass', 'fail'):
        raise ValueError('invalid run identity or outcome')
    if not isinstance(data.get('run_id'), str) or not data['run_id'] or not isinstance(data.get('started_at'), str):
        raise ValueError('missing run identity')
    result.update(run_id=data['run_id'], reason=data.get('reason'), surface=data.get('surface'), campaign=data.get('campaign'), recorded_at=data.get('recorded_at'))
    if data['result'] == 'running':
        result['state'] = 'running'
        return result
    if data['result'] == 'fail':
        result['state'] = 'recorded-fail'
        result['report'] = data.get('report')
        return result
    profile = target.get('radio_verification', {})
    if data.get('surface') not in ('rom', 'native') or data.get('campaign') != 'reverse':
        raise ValueError('unsupported radio coverage')
    if target.get('build') == 'wasm':
        raise ValueError('ROM or native results cannot verify a WASM target')
    if profile.get('surface') != data['surface'] or profile.get('campaign') != data['campaign']:
        result.update(state='stale', reason='verification profile changed')
        return result
    source = data.get('source')
    if not isinstance(source, dict) or source.get('complete') is not True or source.get('unstable') is not False:
        raise ValueError('incomplete source snapshot')
    if source != data.get('source_after') or source.get('fingerprint') != digest(canonical({k: v for k, v in source.items() if k != 'fingerprint'})):
        raise ValueError('source changed during verification')
    artifacts, producer = data.get('artifacts'), data.get('producer')
    for name, records in (('artifacts', artifacts), ('producer', producer)):
        if not isinstance(records, list) or not records or records != data.get(name + '_after'):
            raise ValueError(f'{name} changed or missing during verification')
        if any(not isinstance(x, dict) or not valid_path(x.get('path')) for x in records):
            raise ValueError(f'invalid {name}')
        if len({x['path'] for x in records}) != len(records):
            raise ValueError(f'duplicate {name} paths')
    artifact = data.get('artifact')
    if not valid_path(artifact):
        raise ValueError('missing primary artifact identity')
    expected_artifacts = {artifact}
    if data['surface'] == 'native':
        native_build = data.get('native_build')
        if not valid_path(native_build):
            raise ValueError('missing native runtime identity')
        build = Path(path) / native_build
        if not build.resolve().is_relative_to(Path(path).resolve()):
            raise ValueError('native runtime escapes worktree')
        expected_artifacts.update(str(PurePosixPath(native_build) / name) for name in
                                  ('sf64.o2r', 'starship.o2r', 'gamecontrollerdb.txt', 'default.sav', 'starship.cfg.json'))
        expected_artifacts.update(p.relative_to(path).as_posix() for p in (build / 'mods').glob('*.o2r'))
    if expected_artifacts != {x['path'] for x in artifacts}:
        result.update(state='stale', reason='runtime artifact set changed')
        return result
    required = {'tools/verify_radio_colors.py', 'tools/worktree_status.py', 'tools/radio_verification.py',
                'tools/check_radio_colors_rom.mjs' if data['surface'] == 'rom' else 'tools/check_radio_colors_native.py',
                'browser/crew-chatter.mjs' if data['surface'] == 'rom' else 'tools/radio_colors_rom.py'}
    if not required.issubset({x['path'] for x in producer}):
        raise ValueError('incomplete verifier identity')
    if data.get('exit_code') != 0 or not isinstance(data.get('command'), list) or not data['command']:
        raise ValueError('successful checker execution not recorded')
    matches = [path_hash(path, entry) for entry in [*artifacts, data.get('report'), data.get('checker_report')]]
    producer_root = Path(__file__).resolve().parents[1]
    matches += [path_hash(producer_root, entry) for entry in producer]
    if not snap_cache:
        snap_cache.append(snapshot(path, target, checks))
    current = snap_cache[0]
    if not current['complete'] or source['fingerprint'] != current['fingerprint'] or not all(matches):
        result.update(state='stale', reason='source, verifier, artifact, or report changed')
    else:
        checker_data = json.loads((Path(path) / data['checker_report']['path']).read_text())
        artifact_hash = next(entry['sha256'] for entry in artifacts if entry['path'] == artifact)
        recorded_hash = checker_data.get('rom_sha256' if data['surface'] == 'rom' else 'executable_sha256') if isinstance(checker_data, dict) else None
        if recorded_hash != artifact_hash:
            raise ValueError('checker report does not identify a tested artifact')
        result['coverage'] = validate_report(checker_data, data['surface'], recorded_hash)
        result['state'] = 'recorded-pass'
        result['unbound_reports'] = [p for p in result['unbound_reports'] if p != data['checker_report']['path']]
    result.update(source_head=source['head'], source_dirty=source.get('dirty'), artifacts=artifacts, report=data['report'], command=data['command'])
    return result


def evidence(path, target, check, checks, snap_cache):
    receipt = Path(path) / 'build' / 'worktree-status' / (check['id'] + '.json')
    unbound = [p for p in check['reports'] if (Path(path) / p).is_file()]
    result = {'check': check['id'], 'state': 'unverified', 'provenance': 'unknown', 'unbound_reports': unbound}
    if not receipt.exists():
        return result
    try:
        data = json.loads(receipt.read_text())
        if isinstance(data, dict) and data.get('version') == 2:
            return run_evidence(data, path, target, check, checks, snap_cache, result)
        if not isinstance(data, dict) or data.get('version') != 1 or data.get('target') != target['name'] or data.get('check') != check['id'] or data.get('result') not in ('pass', 'fail') or not isinstance(data.get('recorded_at'), str) or not data['recorded_at'] or not isinstance(data.get('command'), list) or not data['command'] or any(not isinstance(v, str) for v in data['command']) or not isinstance(data.get('source'), dict) or not isinstance(data.get('artifacts'), list) or not data['artifacts']:
            raise ValueError('invalid receipt fields')
        source = data['source']
        if source.get('version') != 1 or not isinstance(source.get('fingerprint'), str) or not isinstance(source.get('head'), str) or source.get('complete') is not True or source.get('unstable') is not False:
            raise ValueError('invalid source snapshot')
        if source['fingerprint'] != digest(canonical({k: v for k, v in source.items() if k != 'fingerprint'})):
            raise ValueError('source fingerprint mismatch')
        file_matches = [path_hash(path, x) for x in [*data['artifacts'], data.get('report')]]
        files_match = all(file_matches)
        if not snap_cache:
            snap_cache.append(snapshot(path, target, checks))
        current = snap_cache[0]
        if not current['complete'] or source['fingerprint'] != current['fingerprint'] or source['head'] != current['head'] or not files_match:
            result['state'] = 'stale'
        else:
            result['state'] = 'recorded-' + data['result']
            result['unbound_reports'] = [p for p in unbound if p != data['report']['path']]
        result.update(recorded_at=data['recorded_at'], source_head=source['head'], source_dirty=source.get('dirty'), artifacts=data['artifacts'], report=data['report'], command=data['command'])
    except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        result.update(state='invalid', error=str(exc))
    return result


def history(repo, head, fix):
    commit = fix['commit']
    if git(repo, 'cat-file', '-e', commit + '^{commit}', check=False).returncode:
        return 'unknown'
    ancestor = git(repo, 'merge-base', '--is-ancestor', commit, head, check=False)
    if ancestor.returncode == 0:
        return 'ancestor'
    if ancestor.returncode != 1:
        return 'unknown'
    parents = git(repo, 'rev-list', '--parents', '-n', '1', commit, check=False)
    parts = decoded(parents.stdout).split()
    if parents.returncode or len(parts) != 2:
        return 'unknown'
    cherry = git(repo, 'cherry', head, commit, parts[1], check=False)
    if cherry.returncode:
        return 'unknown'
    return 'patch-equivalent' if decoded(cherry.stdout).startswith('- ') else 'missing-history'


def build_report(repo, config, selected):
    trees = worktrees(repo)
    by_branch = {}
    for t in trees:
        by_branch.setdefault(t.get('branch'), []).append(t)
    integration = git(repo, 'rev-parse', '--verify', '--quiet', 'refs/heads/' + config['integration_branch'] + '^{commit}', check=False)
    integration_head = decoded(integration.stdout).strip() if integration.returncode == 0 else None
    report = {'integration_branch': config['integration_branch'], 'integration_head': integration_head, 'targets': [], 'unregistered_worktrees': []}
    branches = {'refs/heads/' + t['branch'] for t in config['targets']}
    for tree in trees:
        if tree.get('branch') not in branches:
            report['unregistered_worktrees'].append({'path': tree.get('worktree'), 'branch': tree.get('branch'), 'prunable': bool(tree.get('prunable')), 'head': tree.get('HEAD')})
    all_targets = config['targets']
    for target in all_targets:
        if selected and target['name'] != selected:
            continue
        matches = by_branch.get('refs/heads/' + target['branch'], [])
        live = [t for t in matches if not t.get('prunable')]
        if live:
            matches = live
        item = {'name': target['name'], 'branch': target['branch'], 'planned_branch': target.get('planned_branch'), 'mapping': target.get('mapping'), 'build': target.get('build'), 'campaign': target.get('campaign'), 'availability': 'available', 'fixes': [], 'checks': [], 'possible_overlaps': []}
        report['targets'].append(item)
        if len(matches) != 1:
            item['availability'] = 'missing' if not matches else 'ambiguous'
            continue
        tree = matches[0]
        item['path'] = tree['worktree']
        if tree.get('prunable'):
            item['availability'] = 'prunable'
            continue
        if not Path(item['path']).is_dir():
            item['availability'] = 'unavailable'
            continue
        try:
            head, changes = observation(item['path'])
            actual_branch = textgit(item['path'], 'symbolic-ref', '--quiet', '--short', 'HEAD')
            if actual_branch != target['branch']:
                raise ValueError(f"checked-out branch {actual_branch} does not match {target['branch']}")
            item.update(head=head, dirty=bool(changes), changes=changes, ahead=None, behind=None, branch_only_paths=[])
            if integration_head:
                counts = textgit(repo, 'rev-list', '--left-right', '--count', head + '...' + integration_head).split()
                item['ahead'], item['behind'] = map(int, counts)
                base = git(repo, 'merge-base', head, integration_head, check=False)
                if base.returncode == 0:
                    diff = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--name-only', '-z', decoded(base.stdout).strip(), head, '--')
                    item['branch_only_paths'] = sorted(decoded(x) for x in diff.stdout.split(b'\0') if x)
                else:
                    item['comparison_error'] = 'no merge base with integration branch'
            dirty = changed_paths(changes)
            for fix in config['shared_fixes']:
                state = history(repo, head, fix) if target['name'] in fix['targets'] else 'not-applicable'
                affected = sorted(p for p in dirty if any(p == f or p.startswith(f + '/') or f.startswith(p + '/') for f in fix['paths']))
                item['fixes'].append({'id': fix['id'], 'history': state, 'dirty_paths': affected, 'notes': fix.get('notes')})
            cache = []
            for check in config['checks']:
                if check['id'] in target['checks']:
                    item['checks'].append(evidence(item['path'], target, check, config['checks'], cache))
        except (ValueError, OSError) as exc:
            item['availability'] = 'unavailable'
            item['error'] = str(exc)
    available = [t for t in report['targets'] if t['availability'] == 'available']
    for i, a in enumerate(available):
        ap = set(a['branch_only_paths']) | changed_paths(a['changes'])
        for b in available[i + 1:]:
            bp = set(b['branch_only_paths']) | changed_paths(b['changes'])
            shared = sorted(ap & bp)
            if shared:
                a['possible_overlaps'].append({'target': b['name'], 'paths': shared})
                b['possible_overlaps'].append({'target': a['name'], 'paths': shared})
    return report


def attention(report):
    if not report['integration_head']:
        return True
    for t in report['targets']:
        if t['availability'] != 'available' or t.get('dirty') or t.get('comparison_error') or t['possible_overlaps']:
            return True
        if any(f['history'] in ('missing-history', 'unknown') or f['dirty_paths'] for f in t['fixes']):
            return True
        if any(c['state'] != 'recorded-pass' for c in t['checks']):
            return True
    return False


def print_report(report):
    print('Integration:', report['integration_branch'], report['integration_head'] or '(unavailable)')
    for t in report['targets']:
        print(f"\n{t['name']} [{t['branch']}]: {t['availability']}")
        print(f"  Mapping: {t['mapping']}; planned branch: {t['planned_branch']}; build: {t['build']}; campaign: {t['campaign']}")
        if t['availability'] != 'available':
            if t.get('error'): print('  ', t['error'])
            continue
        print(f"  {t['path']}  HEAD {t['head'][:12]}  ahead/behind {t['ahead']}/{t['behind']}")
        for change in t['changes'][:5]:
            print(' ', change['status'], repr(change['path']), ('<- ' + repr(change['original_path'])) if 'original_path' in change else '')
        if len(t['changes']) > 5: print(f"  ... {len(t['changes']) - 5} more changes")
        print(f"  Branch-only paths ({len(t['branch_only_paths'])}): {t['branch_only_paths'][:5]}")
        for f in t['fixes']:
            print(f"  Fix {f['id']}: history {f['history']}" + (f"; dirty affected paths {f['dirty_paths'][:5]}" if f['dirty_paths'] else ''))
            if f['notes']: print(f"    {f['notes']}")
        for c in t['checks']:
            print(f"  Check {c['check']}: {c['state']}; provenance {c['provenance']}" + (f"; unbound reports {c['unbound_reports'][:5]}" if c['unbound_reports'] else ''))
            if c.get('source_head'):
                print(f"    Recorded source {c['source_head'][:12]}, dirty={c['source_dirty']}; report {c['report']['path']}; artifacts {[x['path'] for x in c['artifacts'][:5]]}")
            if c.get('reason') or c.get('error'):
                print('   ', c.get('reason') or c.get('error'))
        for overlap in t['possible_overlaps']:
            print(f"  Possible overlap with {overlap['target']} ({len(overlap['paths'])} paths): {overlap['paths'][:5]}")
        if t.get('comparison_error'): print(' ', t['comparison_error'])
    if report['unregistered_worktrees']:
        print(f"\nUnregistered worktrees ({len(report['unregistered_worktrees'])}):")
        for t in report['unregistered_worktrees'][:5]:
            print(' ', t['branch'] or '(detached)', t['path'], '(prunable)' if t['prunable'] else '')
    print('\nHistory is not behavior evidence. Manually copied or reverted fixes require checks. Recorded checks are external attestations.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    parser.add_argument('--registry', default=str(Path(__file__).with_name('worktrees.json')))
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--target')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--snapshot', metavar='TARGET')
    args = parser.parse_args()
    try:
        config = registry(args.registry)
        selected = args.snapshot or args.target
        if args.snapshot and args.target and args.target != args.snapshot:
            raise ValueError('--target and --snapshot must select the same target')
        if selected and selected not in {t['name'] for t in config['targets']}:
            raise ValueError(f'unknown target: {selected}')
        report = build_report(args.repo, config, None if not args.snapshot else selected)
        if args.snapshot:
            item = report['targets'][0]
            if item['availability'] != 'available':
                raise ValueError(f"target {selected} is {item['availability']}")
            target = next(t for t in config['targets'] if t['name'] == selected)
            result = snapshot(item['path'], target, config['checks'])
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 1 if args.strict and not result['complete'] else 0
        if selected:
            report['targets'] = [t for t in report['targets'] if t['name'] == selected]
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=True))
        else:
            print_report(report)
        return 1 if args.strict and attention(report) else 0
    except (ValueError, OSError) as exc:
        print(f'worktree-status: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
