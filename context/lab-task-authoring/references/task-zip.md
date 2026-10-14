# cJudge Task ZIP v1

Use this format for **Import task ZIP**. The older **Replace cases from ZIP** control accepts only flat `1.in`/`1.out` pairs and does not import task settings.

```
task.zip
├── manifest.json
└── cases/
    ├── 1.in
    ├── 1.out
    ├── 2.in
    └── 2.out
```

`manifest.json` is UTF-8 JSON. Use this complete example and change values for the task:

```json
{
  "format": "cjudge-task",
  "version": 1,
  "config": {
    "title": "Add two integers",
    "statement": "Read two integers and print their sum.",
    "scoring": "partial",
    "checker": {
      "kind": "tokens",
      "source": "",
      "ignore_final_newline": false,
      "ignore_case": false,
      "absolute_tolerance": "0",
      "relative_tolerance": "0"
    },
    "banned_identifiers": [],
    "cpu_seconds": 2,
    "wall_seconds": 6,
    "memory_mib": 256,
    "stack_mib": 8,
    "stdout_mib": 10
  },
  "case_count": 2
}
```

For a Python checker, set `kind` to `python` and put its source in `checker.source`; other checker options must remain at their defaults. Omit `maximum_marks`: set marks when assigning the imported revision to a lab. Include exactly `cases/1.in` and `cases/1.out` through `cases/N.in` and `cases/N.out`, with no gaps or other entries. Preserve input/answer bytes. Use regular, unencrypted stored or deflated ZIP entries. Limits: ZIP 17 MiB; manifest 1 MiB; 1–100 pairs; each input or answer 1 MiB; all case bytes 16 MiB. Import makes a draft; review and publish it explicitly.

To package existing case bytes in Python, use `zipfile.ZipFile(..., 'w', compression=zipfile.ZIP_STORED)`; write `manifest.json` with `json.dumps(manifest).encode('utf-8')`, then write each pair under `cases/`. `src/cjudge/tasks/bundle.py` is the authoritative builder and parser when working in this repository.

## Generate then package

The supplied [`build-task-zip.py`](../scripts/build-task-zip.py) compiles the reference C program, generates one case per consecutive seed, runs the reference on each input, and writes this ZIP. It calls cJudge's isolated authoring runner. Run it inside the standalone `judge` container with the task files mounted read-only and an output directory mounted writable:

```sh
docker compose build judge
mkdir -p task-output
docker compose --profile sandbox run --rm --no-deps \
  -v "$PWD:/workspace:ro" -v "$PWD/task-output:/bundle" judge \
  python /workspace/context/lab-task-authoring/scripts/build-task-zip.py \
  --config /workspace/task-config.json \
  --generator /workspace/generator.py --reference /workspace/reference.c \
  --seed 0 --count 10 --output /bundle/task.zip
```

Replace file paths with your task files. Set `--language c` for a C generator. The Python generator reads its seed from `sys.argv[1]`; cJudge seeds `random` automatically inside the isolate. A standalone generator script run elsewhere must seed `random` itself. Generator stdout becomes case input; reference stdout becomes expected output. If compilation, generation, reference execution, or validation fails, no ZIP is written. Keep generator/reference sources separately: the ZIP contains their resulting cases, not those programs. Review case previews and check expected answers independently before import.
`task-config.json` contains only the `config` object from the manifest example; the script adds `format`, `version`, and `case_count`.
