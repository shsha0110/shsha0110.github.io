#!/usr/bin/env python3
"""Tier 1 기계적 정규화 — shsha0110.github.io 블로그 포스트 일괄 정리.

대상 (전부 판단 불필요, .claude/blog-house-style.md §A/§D 근거):
  1. theme: 줄 삭제           (format.html 덮어쓰기 방지)
  2. date: 줄 삭제            (정렬 무관, 카드 표시 일관성)
  3. 작은따옴표 -> 큰따옴표    (title/description/author)
  4. math: true 추가          (누락된 1건)
  5. title 번호 제로패딩       ([Data Mining] 2. -> 02.)
  6. 본문 헤딩 +1 이동 (# -> ##) — "단순형"에만 적용:
       - 최상위가 # 하나뿐이고
       - 첫 h1 이전에 ## 프리앰블이 없고 (있으면 Tier 2, 손대지 않음)
       - +1 이동해도 h6을 넘지 않는 경우 (넘으면 Tier 2, 손대지 않음)

Tier 2/3 (categories 정규화, 프리앰블 혼재 헤딩, h6 초과, description 누락,
외부 이미지 핫링크)는 이 스크립트가 건드리지 않는다. dry-run 리포트에
전부 나열되며, 사용자 결정 후 별도 처리한다.

사용법:
  python3 normalize_tier1.py                 # dry-run (기본, 파일 미변경)
  python3 normalize_tier1.py --apply         # 실제 적용
  python3 normalize_tier1.py --apply --only path/to/index.qmd   # 단일 파일만
"""
import argparse
import pathlib
import re
import sys
from dataclasses import dataclass, field

REPO = pathlib.Path(__file__).resolve().parents[2]
POSTS = REPO / "posts"

FENCE = re.compile(r"^\s*```")
CALLOUT_OPEN = re.compile(r"^:::+\s*\{\.callout-")
DIV_CLOSE = re.compile(r"^:::+\s*$")
HEADING = re.compile(r"^(#{1,6})(\s+)(\S.*)$")

QUOTE_KEYS = ("title", "description", "author")


def split_line_ending(line):
    """(개행 없는 본문, 원래 줄 끝) 반환. 정규식으로 줄을 재조립할 때 \\s* 같은
    탐욕적 패턴이 줄바꿈 문자를 삼켜버리는 사고를 원천 차단하기 위해, 줄 끝을
    먼저 분리해 두고 본문에만 정규식을 적용한 뒤 끝에 그대로 재부착한다."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


@dataclass
class FileReport:
    path: pathlib.Path
    actions: list = field(default_factory=list)   # 적용된 Tier1 액션 설명 (사람이 읽는 텍스트)
    skips: list = field(default_factory=list)      # Tier2/3 로 남긴 이유
    changed: bool = False


def split_frontmatter(text):
    """반환: (fm_lines, body_lines) — 둘 다 개행 포함 리스트. 실패 시 (None, None)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, None
    for j in range(1, len(lines)):
        if lines[j].strip() == "---":
            return lines[1:j], lines[j + 1:]
    return None, None


def find_body_headings(body_lines):
    """코드블록/callout 내부를 제외한 (line_idx, level) 목록을 순서대로 반환."""
    in_fence = in_callout = False
    entries = []
    for i, line in enumerate(body_lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if CALLOUT_OPEN.match(line):
            in_callout = True
            continue
        if in_callout and DIV_CLOSE.match(line):
            in_callout = False
            continue
        if in_callout:
            continue
        m = HEADING.match(line)
        if m:
            entries.append((i, len(m.group(1))))
    return entries


def apply_yaml_fixes(fm_lines, report):
    """theme 삭제 / date 삭제 / 따옴표 통일 / math 추가 / title 제로패딩.

    fm_lines를 제자리에서 바꾸지 않고 새 리스트를 반환한다.
    """
    fm_lines = list(fm_lines)

    # 1. theme: 줄 삭제
    kept = []
    for line in fm_lines:
        if re.match(r"^\s*theme:\s*\S", line):
            report.actions.append("theme: 줄 삭제")
            continue
        kept.append(line)
    fm_lines = kept

    # 2. date: 줄 삭제 (최상위 키만 — 들여쓰기 없이 정확히 'date:'로 시작)
    kept = []
    for line in fm_lines:
        if re.match(r"^date:\s*\S", line):
            report.actions.append("date: 줄 삭제")
            continue
        kept.append(line)
    fm_lines = kept

    # 3. 작은따옴표 -> 큰따옴표 (title/description/author)
    for idx, line in enumerate(fm_lines):
        core, ending = split_line_ending(line)
        m = re.match(r"^(" + "|".join(QUOTE_KEYS) + r"):\s*'(.*)'$", core)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        val = val.replace("''", "'")  # YAML 작은따옴표 이스케이프 복원
        if '"' in val:
            report.skips.append(f"{key}: 값에 큰따옴표가 포함되어 자동 변환 보류 — 수동 확인 필요")
            continue
        fm_lines[idx] = f'{key}: "{val}"{ending}'
        report.actions.append(f"{key}: 작은따옴표 -> 큰따옴표")

    # 4. math: true 추가 (없으면 code-fold 다음 줄에 삽입)
    fm_text = "".join(fm_lines)
    if not re.search(r"^\s*math:\s*true", fm_text, re.M):
        for idx, line in enumerate(fm_lines):
            if re.match(r"^\s*code-fold:", line):
                indent = re.match(r"^(\s*)", line).group(1)
                fm_lines.insert(idx + 1, f"{indent}math: true\n")
                report.actions.append("math: true 추가")
                break
        else:
            report.skips.append("math: true 누락이지만 code-fold 줄을 찾지 못함 — 수동 확인 필요")

    # 5. title 번호 제로패딩: "[...] N. " 의 N이 한 자리면 0N으로
    for idx, line in enumerate(fm_lines):
        core, ending = split_line_ending(line)
        m = re.match(r'^(title:\s*")(\[[^\]]+\]\s+)(\d)(\.\s.*")$', core)
        if m:
            prefix, bracket, num, rest = m.groups()
            fm_lines[idx] = f"{prefix}{bracket}0{num}{rest}{ending}"
            report.actions.append(f"title 번호 제로패딩: {num}. -> 0{num}.")
            break

    return fm_lines


def apply_heading_shift(body_lines, report):
    """단순형 파일만 본문 헤딩을 +1 이동한다. 그 외는 이유를 report.skips에 남기고 그대로 반환."""
    entries = find_body_headings(body_lines)
    if not entries:
        return body_lines  # 헤딩 없음 — 손댈 것 없음

    min_level = min(lvl for _, lvl in entries)
    if min_level >= 2:
        return body_lines  # 이미 ## 최상위 — 규격 준수, 변경 없음

    # min_level == 1
    first_h1_pos = next(i for i, (_, lvl) in enumerate(entries) if lvl == 1)
    preamble = entries[:first_h1_pos]
    if preamble:
        levels = sorted(set(lvl for _, lvl in preamble))
        report.skips.append(
            f"헤딩 이동 보류 — 첫 h1 이전에 레벨 {levels} 프리앰블 헤딩 {len(preamble)}개 존재 (Tier 2, 개별 확인)"
        )
        return body_lines

    max_level = max(lvl for _, lvl in entries)
    if max_level + 1 > 6:
        report.skips.append(
            f"헤딩 이동 보류 — 이동 시 h{max_level + 1} 발생, h6 초과 (Tier 2, 개별 확인)"
        )
        return body_lines

    body_lines = list(body_lines)
    for line_idx, _ in entries:
        line = body_lines[line_idx]
        assert HEADING.match(line), f"헤딩 재매칭 실패: {line!r}"
        # 정규식 그룹으로 줄을 재조립하지 않고 원본 줄 앞에 '#' 하나만 붙인다.
        # 그룹 재조립(f"#{hashes}{sep}{rest}")은 원본의 줄바꿈 문자를 캡처하지 못해
        # 유실시키고, 그 결과 join() 시 다음 줄(대개 빈 줄)이 흡수되어 사라진다.
        body_lines[line_idx] = "#" + line
    report.actions.append(f"본문 헤딩 {len(entries)}개 +1 이동 (최상위 h1 -> h2, 최심부 h{max_level} -> h{max_level + 1})")
    return body_lines


def process_file(path: pathlib.Path):
    """파일을 처리해 (report, new_text_or_None) 반환. None이면 변경 없음."""
    report = FileReport(path=path)
    original = path.read_text(encoding="utf-8")
    fm_lines, body_lines = split_frontmatter(original)
    if fm_lines is None:
        report.skips.append("프론트매터 파싱 실패 — 수동 확인 필요")
        return report, None

    fm_lines = apply_yaml_fixes(fm_lines, report)
    body_lines = apply_heading_shift(body_lines, report)

    if not report.actions:
        return report, None

    report.changed = True
    new_text = "---\n" + "".join(fm_lines) + "---\n" + "".join(body_lines)
    return report, new_text


def collect_targets(only=None):
    if only:
        p = pathlib.Path(only)
        if not p.is_absolute():
            p = REPO / only
        return [p]
    return sorted(POSTS.rglob("index.qmd"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 수정한다 (기본은 dry-run)")
    ap.add_argument("--only", help="단일 파일만 처리 (저장소 루트 기준 상대경로 또는 절대경로)")
    ap.add_argument("--quiet", action="store_true", help="적용/보류 사항이 없는 파일은 리포트에서 생략 (기본 동작과 동일하지만 skip-only 파일도 생략)")
    args = ap.parse_args()

    targets = collect_targets(args.only)
    n_changed = n_skip_only = n_untouched = 0
    action_counts = {}
    skip_counts = {}

    for path in targets:
        report, new_text = process_file(path)
        rel = path.relative_to(REPO)

        if report.actions or (report.skips and not args.quiet):
            print(f"\n{rel}")
            for a in report.actions:
                print(f"  [적용] {a}")
                label = a.split(":")[0].strip()
                action_counts[label] = action_counts.get(label, 0) + 1
            for s in report.skips:
                print(f"  [보류] {s}")
                skip_counts[s] = skip_counts.get(s, 0) + 1

        if new_text is not None:
            n_changed += 1
            if args.apply:
                path.write_text(new_text, encoding="utf-8")
        elif report.skips:
            n_skip_only += 1
        else:
            n_untouched += 1

    print("\n" + "=" * 70)
    print(f"대상 파일               : {len(targets)}")
    print(f"변경 {'적용됨       ' if args.apply else '예정(dry-run)'} : {n_changed}")
    print(f"보류만 있음 (미변경)     : {n_skip_only}")
    print(f"완전 무관 (미변경)       : {n_untouched}")

    if action_counts:
        print("\n적용된 액션 집계:")
        for label, n in sorted(action_counts.items(), key=lambda x: -x[1]):
            print(f"  {label:30s} {n:4d}건")

    if skip_counts:
        print("\n보류된 사항 집계 (Tier 2/3 — 이 스크립트는 처리하지 않음):")
        for s, n in sorted(skip_counts.items(), key=lambda x: -x[1]):
            print(f"  {n:4d}건  {s}")

    if not args.apply and n_changed:
        print("\n실제 적용하려면 --apply 를 붙여 재실행하세요.")


if __name__ == "__main__":
    sys.exit(main())
