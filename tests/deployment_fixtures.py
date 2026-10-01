"""Deterministic M9 programs; execute only through the judge's isolate boundary."""


def fixtures() -> list[tuple[str, str, list[tuple[bytes, bytes]]]]:
    arithmetic = [(f'{i} {-i * 3}\n'.encode(), f'{-2 * i}\n'.encode()) for i in range(10)]
    arrays, strings, sorting, matrices = [], [], [], []
    for seed in range(10):
        values = [(i * 37 + seed * 13) % 1000 - 500 for i in range(100 + seed * 100)]
        data = f'{len(values)}\n' + ' '.join(map(str, values)) + '\n'
        arrays.append((data.encode(), f'{sum(values)}\n'.encode()))
        sorting.append((data.encode(), (' '.join(map(str, sorted(values))) + '\n').encode()))
        word = ('abcXYZ012' * (seed + 1)) + 'end'
        strings.append((f'{word}\n'.encode(), f'{word[::-1]}\n'.encode()))
        size = seed + 2
        cells = [(i + seed) % 17 - 8 for i in range(size * size)]
        matrices.append(((f'{size}\n' + ' '.join(map(str, cells)) + '\n').encode(),
            (' '.join(str(sum(cells[row * size + col] for row in range(size))) for col in range(size)) + '\n').encode()))
    return [
        ('Arithmetic', '#include <stdio.h>\nint main(void){int a,b;scanf("%d%d",&a,&b);printf("%d\\n",a+b);}', arithmetic),
        ('Arrays', '#include <stdio.h>\nint main(void){int n,x,s=0;scanf("%d",&n);while(n--){scanf("%d",&x);s+=x;}printf("%d\\n",s);}', arrays),
        ('Strings', '#include <stdio.h>\n#include <string.h>\nint main(void){char s[1024];scanf("%1023s",s);for(int i=(int)strlen(s)-1;i>=0;i--)putchar(s[i]);puts("");}', strings),
        ('Sorting', '#include <stdio.h>\n#include <stdlib.h>\nint cmp(const void*a,const void*b){int x=*(const int*)a,y=*(const int*)b;return (x>y)-(x<y);}\nint main(void){int n,a[2048];scanf("%d",&n);for(int i=0;i<n;i++)scanf("%d",a+i);qsort(a,n,sizeof(int),cmp);for(int i=0;i<n;i++)printf("%s%d",i?" ":"",a[i]);puts("");}', sorting),
        ('Matrices', '#include <stdio.h>\nint main(void){int n,x,s[32]={0};scanf("%d",&n);for(int r=0;r<n;r++)for(int c=0;c<n;c++){scanf("%d",&x);s[c]+=x;}for(int c=0;c<n;c++)printf("%s%d",c?" ":"",s[c]);puts("");}', matrices),
    ]
