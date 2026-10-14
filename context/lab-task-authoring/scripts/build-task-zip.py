"""Build a task ZIP from local sources through cJudge's isolated authoring runner."""

import argparse
from pathlib import Path

from cjudge.tasks.authoring import GenerationConfig, compile_source, generate_case
from cjudge.tasks.bundle import build
from cjudge.tasks.grading import TaskConfig


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate and package one cJudge task')
    parser.add_argument('--config', type=Path, required=True, help='TaskConfig JSON (no marks)')
    parser.add_argument('--generator', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True, help='Reference C source')
    parser.add_argument('--language', choices=('python', 'c'), default='python')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    config = TaskConfig.model_validate_json(args.config.read_bytes())
    generation = GenerationConfig(language=args.language, generator=args.generator.read_text(),
        reference=args.reference.read_text(), seed=args.seed, count=args.count)
    reference = compile_source(generation.reference, 'reference')
    generator = compile_source(generation.generator, 'generator') if args.language == 'c' else None
    cases = [generate_case(generation, args.seed + number, reference, generator)
             for number in range(args.count)]
    payload = build(config.model_dump(mode='json', exclude={'maximum_marks'}), cases)
    args.output.write_bytes(payload)
    print(f'Created {args.output} with {len(cases)} cases')


if __name__ == '__main__':
    main()
