#!/usr/bin/env python3
"""Convert Paul PLAN.md files to GSD format."""

import sys
import re
from pathlib import Path


def extract_frontmatter(text):
    match = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
    if not match:
        return {}, text.strip()
    fm_text = match.group(1)
    rest = text[match.end():].strip()
    fm = {}
    for line in fm_text.split('\n'):
        line = line.strip()
        if ':' in line and not line.startswith('#'):
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val == '[]':
                fm[key] = []
            elif val.startswith('[') and val.endswith(']'):
                items = val[1:-1].split(',')
                fm[key] = [i.strip().strip('"').strip("'") for i in items if i.strip()]
            elif val == 'true':
                fm[key] = True
            elif val == 'false':
                fm[key] = False
            else:
                fm[key] = val
    return fm, rest


def extract_tag_content(text, tag_name):
    pattern = rf'<{tag_name}>(.*?)</{tag_name}>'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def extract_task_blocks(text):
    tasks_match = re.search(r'<tasks>(.*?)</tasks>', text, re.DOTALL)
    if not tasks_match:
        return []
    tasks_text = tasks_match.group(1)
    task_blocks = re.findall(r'<task[^>]*>(.*?)</task>', tasks_text, re.DOTALL)
    return [b.strip() for b in task_blocks]


def parse_task(block):
    name_m = re.search(r'<name>(.*?)</name>', block, re.DOTALL)
    files_m = re.search(r'<files>(.*?)</files>', block, re.DOTALL)
    action_m = re.search(r'<action>(.*?)</action>', block, re.DOTALL)
    verify_m = re.search(r'<verify>(.*?)</verify>', block, re.DOTALL)
    done_m = re.search(r'<done>(.*?)</done>', block, re.DOTALL)
    return {
        'name': name_m.group(1).strip() if name_m else '',
        'files': files_m.group(1).strip().replace('\n', ', ') if files_m else '',
        'action': action_m.group(1).strip() if action_m else '',
        'verify': verify_m.group(1).strip() if verify_m else '',
        'done': done_m.group(1).strip() if done_m else '',
    }


def extract_objective(text):
    obj_text = extract_tag_content(text, 'objective') or ''
    goal_m = re.search(r'## Goal\n(.*?)(?:\n|$)', obj_text, re.DOTALL)
    goal = goal_m.group(1).strip().rstrip() if goal_m else ''
    purpose_m = re.search(r'## Purpose\n(.*?)\n(?:## Output|</objective>)', obj_text, re.DOTALL)
    purpose = purpose_m.group(1).strip().rstrip() if purpose_m else ''
    return goal, purpose


def extract_acceptance_criteria(text):
    ac_text = extract_tag_content(text, 'acceptance_criteria') or ''
    pattern = r'## (AC-\d+:\s*)(.*?)\n```gherkin\n(.*?)```'
    matches = re.findall(pattern, ac_text, re.DOTALL)
    return [(ac_id + ': ' + title.strip(), desc.strip()) for ac_id, title, desc in matches]


def extract_boundaries(text):
    bnd = extract_tag_content(text, 'boundaries') or ''
    do_not_change = []
    scope_limits = []
    dnc_m = re.search(r'## DO NOT CHANGE\n(.*?)(?=## SCOPE LIMITS|$)', bnd, re.DOTALL)
    if dnc_m:
        lines = [l.strip() for l in dnc_m.group(1).strip().split('\n') if l.strip()]
        do_not_change = [l.lstrip('- ').lstrip('* ') for l in lines]
    sl_m = re.search(r'## SCOPE LIMITS\n(.*?)(?=</boundaries>|$)', bnd, re.DOTALL)
    if sl_m:
        lines = [l.strip() for l in sl_m.group(1).strip().split('\n') if l.strip()]
        scope_limits = [l.lstrip('- ').lstrip('* ') for l in lines]
    return do_not_change, scope_limits


def extract_verification(text):
    v_text = extract_tag_content(text, 'verification') or ''
    items = [l.strip().lstrip('- ') for l in v_text.split('\n') if l.strip() and not l.strip().startswith('#')]
    return items


def extract_success_criteria(text):
    sc_text = extract_tag_content(text, 'success_criteria') or ''
    items = [l.strip().lstrip('- ') for l in sc_text.split('\n') if l.strip() and not l.strip().startswith('#')]
    return items


def classify_files(files_modified_str):
    lines = [l.strip().strip('- ').strip("'").strip('"') for l in files_modified_str.split('\n') if l.strip()]
    created, modified = [], []
    for f in lines:
        if '(new)' in f:
            created.append(f.replace(' (new)', '').strip())
        else:
            modified.append(f)
    return created, modified


def generate_gsd_plan(paul_text):
    fm, body = extract_frontmatter(paul_text)

    phase_slug = fm.get('phase', 'unknown')
    plan_num = fm.get('plan', '01')
    plan_type = fm.get('type', 'execute')
    wave = fm.get('wave', '1')
    depends_on = fm.get('depends_on', [])
    files_modified_str = fm.get('files_modified', '')

    goal, purpose = extract_objective(body)
    acs = extract_acceptance_criteria(body)
    tasks_raw = extract_task_blocks(body)
    do_not_change, scope_limits = extract_boundaries(body)
    verification_items = extract_verification(body)
    success_items = extract_success_criteria(body)

    created_files, modified_files = classify_files(files_modified_str) if isinstance(files_modified_str, str) else ([], [])

    tags = []
    if plan_type == 'tdd':
        tags.append('tdd')
    elif plan_type == 'research':
        tags.append('research')
    elif plan_type == 'execute':
        tags.append('implementation')

    subsystem_map = {
        'parameter-cards': 'Card System',
        'llm-story-generation': 'LLM Integration',
        'streaming-tts': 'TTS Pipeline',
        'cover-images': 'Image Generation',
        'fix-pause-resume': 'Audio Control',
        'foundation-verification': 'Hardware Verification',
        'fix-piper-tts-dependency': 'Dependencies',
        'documentation-cleanup': 'Documentation',
        'test-coverage': 'Testing',
        'test-coverage-ui': 'UI Testing',
    }
    subsystem = subsystem_map.get(phase_slug.replace('-', '_'), phase_slug)

    dep_requires = [f'Phase {d}' for d in depends_on] if depends_on else []
    dep_affects = ['']

    created_section = '\n'.join(f'      - path: "{cf}"' for cf in created_files) or '(none)'
    modified_section = '\n'.join(f'      - path: "{mf}"\n        changes: ["See task details"]' for mf in modified_files) or '(none)'

    decisions = []
    for tb in tasks_raw:
        parsed = parse_task(tb)
        if 'Avoid:' in parsed['action']:
            avoid_section = parsed['action'].split('Avoid:')[1]
            for line in avoid_section.strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    decisions.append(line.lstrip('- ').lstrip('* '))

    ac_section = ''
    for title, desc in acs:
        ac_section += f'\n### {title}\n{desc}\n'

    task_breakdown = ''
    for i, tb in enumerate(tasks_raw):
        parsed = parse_task(tb)
        if parsed['name']:
            task_breakdown += f'\n**Task {i+1}: {parsed["name"]}** ✅\n'
            action_lines = [l for l in parsed['action'].split('\n') if l.strip()][:5]
            for al in action_lines:
                task_breakdown += f'- {al}\n'
            task_breakdown += '\n'

    ver_checklist = ''
    for item in verification_items:
        ver_checklist += f'\n- [ ] {item}'

    sc_formatted = ''
    for item in success_items:
        sc_formatted += f'- {item}\n'

    plan_title = 'Phase {} Plan {}'.format(phase_slug.replace('-', ' ').title(), plan_num)

    parts = []
    parts.append('---')
    parts.append('phase: {}'.format(phase_slug))
    parts.append('plan: {}'.format(plan_num))
    parts.append('type: {}'.format(plan_type))
    parts.append('wave: {}'.format(wave))
    parts.append('subsystem: {}'.format(subsystem))
    parts.append("tags: [{}]".format(', '.join(tags)))
    parts.append('requirements: []')
    parts.append('dependency_graph:')
    parts.append('  requires: {}'.format(dep_requires if dep_requires else '[]'))
    parts.append('  provides: (none)')
    parts.append("  affects: {}".format(dep_affects if any(dep_affects) else '[]'))
    parts.append('')
    parts.append('key_files:')
    parts.append('  created:')
    for cf in created_files:
        parts.append('      - path: "{}"'.format(cf))
    parts.append('  modified:')
    for mf in modified_files:
        parts.append('      - path: "{}"'.format(mf))
    parts.append('')
    parts.append("decisions: {}".format(decisions[:5] if decisions else '[]'))
    parts.append('')
    parts.append('metrics:')
    parts.append('  duration: "TBD"')
    parts.append('  tasks_completed: 0')
    parts.append('---')
    parts.append('')
    parts.append('# {}'.format(plan_title))
    parts.append('')
    parts.append(goal)
    parts.append('')
    parts.append('## One-Liner')
    parts.append('')
    parts.append(purpose)
    parts.append('')
    parts.append('## Acceptance Criteria')
    parts.append(ac_section)
    parts.append('## Task Breakdown')
    parts.append(task_breakdown)
    parts.append('## Boundaries')
    parts.append('')
    if do_not_change:
        parts.append('### DO NOT CHANGE')
        for dnc in do_not_change:
            parts.append('- {}'.format(dnc))
    else:
        parts.append('(none specified)')
    parts.append('')
    if scope_limits:
        parts.append('### Scope Limits')
        for sl in scope_limits:
            parts.append('- {}'.format(sl))
    else:
        parts.append('(none specified)')
    parts.append('')
    parts.append('## Verification')
    parts.append(ver_checklist)
    parts.append('')
    parts.append('## Success Criteria')
    parts.append(sc_formatted)

    return '\n'.join(parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: convert_paul_to_gsd.py <paul-plan-file> [output-path]")
        sys.exit(1)

    paul_file = Path(sys.argv[1])
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    text = paul_file.read_text()
    gsd = generate_gsd_plan(text)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(gsd + '\n')
        print("Written to {}".format(out))
    else:
        print(gsd)


if __name__ == '__main__':
    main()
