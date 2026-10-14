"""M26 real-isolate gate: docker compose run --rm judge python tests/cpp17_gate.py."""
from cjudge import runner
from cjudge.tasks.authoring import GenerationConfig, compile_source, generate_case
from cjudge.tasks.bundle import build, parse


def main() -> None:
    runner.configure_box(0)
    cpp = br'''
#include <iostream>
#include <vector>
#include <utility>
int main() {
    std::vector<int> values{2, 3};
    auto [a,b] = std::pair{values[0], values[1]};
    if constexpr(sizeof(int) >= 2) std::cout << a+b << "\n";
}
'''
    compiled = runner.compile_source(cpp, 'cpp17')
    assert compiled.verdict == 'OK', compiled.stderr
    result = runner.execute(compiled.executable)
    assert result.verdict == 'OK' and result.stdout == b'5\n', result
    assert runner.compile_source(b'int main(){ invalid_cpp }', 'cpp17').verdict == 'CE'
    loop = runner.compile_source(b'int main(){for(;;){}}', 'cpp17')
    assert loop.verdict == 'OK'
    assert runner.execute(loop.executable, limits=runner.Limits(cpu_seconds=.1, wall_seconds=1)).verdict == 'TLE'
    legacy = runner.compile_c(b'int main(void){return 0;}')
    assert legacy.verdict == 'OK' and runner.execute(legacy.executable).verdict == 'OK'
    config = GenerationConfig(language='cpp', reference_language='cpp', seed=2, count=1,
        generator='#include <iostream>\n#include <cstdlib>\nint main(int n,char**a){std::cout<<std::atoi(a[1])<<"\\n";}',
        reference='#include <iostream>\nint main(){int n;std::cin>>n;std::cout<<n*2<<"\\n";}')
    reference = compile_source(config.reference, 'reference', 'cpp')
    generator = compile_source(config.generator, 'generator', 'cpp')
    pair = generate_case(config, 2, reference, generator)
    assert pair == (b'2\n', b'4\n')
    python = config.model_copy(update={'language': 'python', 'generator': 'import sys; print(sys.argv[1])'})
    assert generate_case(python, 3, reference) == (b'3\n', b'6\n')
    payload = build({'title': 'CPP', 'languages': ['cpp17']}, [pair])
    assert parse(payload)[0]['languages'] == ['cpp17']
    print('PASS: C++17 STL, compilation errors, timeout recovery, legacy C, C++/Python authoring and task ZIP v2')


if __name__ == '__main__':
    main()
