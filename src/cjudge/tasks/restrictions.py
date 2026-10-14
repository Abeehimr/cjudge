"""Bounded lexical scan of source identifiers; teaching policy, not C preprocessing."""


def first_banned(source: bytes, names: list[str]) -> tuple[str, int] | None:
    if not names:
        return None
    if len(source) > 65536:
        raise ValueError('Source exceeds 64 KiB')
    banned = {name.encode('ascii') for name in names}
    logical = bytearray()
    line_numbers = []
    line = 1
    index = 0
    while index < len(source):
        if source[index] == 92 and index + 1 < len(source):
            width = 2 if source[index + 1] == 10 else 3 if source[index + 1:index + 3] == b'\r\n' else 0
            if width:
                index += width
                line += 1
                continue
        logical.append(source[index])
        line_numbers.append(line)
        if source[index] == 10 or source[index] == 13 and (index + 1 == len(source) or source[index + 1] != 10):
            line += 1
        index += 1

    data = bytes(logical)
    index = 0
    line_start = True
    directive = False
    header_next = False
    while index < len(data):
        char = data[index]
        if char == 10 or char == 13 and (index + 1 == len(data) or data[index + 1] != 10):
            line_start, directive, header_next = True, False, False
            index += 1
        elif char in b' \t\r\v\f':
            index += 1
        elif char == 35 and line_start:
            directive, line_start = True, False
            index += 1
        elif char == 47 and data[index:index + 2] == b'//':
            index = data.find(b'\n', index + 2)
            if index < 0:
                break
        elif char == 47 and data[index:index + 2] == b'/*':
            end = data.find(b'*/', index + 2)
            if b'\n' in data[index:end if end >= 0 else len(data)] or b'\r' in data[index:end if end >= 0 else len(data)]:
                line_start = True
            index = len(data) if end < 0 else end + 2
        elif header_next and char == 60:
            end = data.find(b'>', index + 1)
            newline = data.find(b'\n', index + 1)
            index = end + 1 if end >= 0 and (newline < 0 or end < newline) else (newline if newline >= 0 else len(data))
            header_next = False
        elif char in (34, 39):
            quote = char
            index += 1
            while index < len(data) and data[index] != quote:
                index += 2 if data[index] == 92 else 1
            index += 1
            line_start = False
        elif char == 46 and index + 1 < len(data) and 48 <= data[index + 1] <= 57 or 48 <= char <= 57:
            index += 1
            while index < len(data) and (data[index] in b'._' or 48 <= data[index] <= 57 or
                    65 <= data[index] <= 90 or 97 <= data[index] <= 122 or
                    data[index] in b'+-' and data[index - 1] in b'eEpP'):
                index += 1
            line_start = False
        elif char == 95 or 65 <= char <= 90 or 97 <= char <= 122 or char >= 128:
            start = index
            index += 1
            while index < len(data) and (data[index] == 95 or 48 <= data[index] <= 57 or
                    65 <= data[index] <= 90 or 97 <= data[index] <= 122 or data[index] >= 128):
                index += 1
            token = data[start:index]
            if directive:
                header_next = token in (b'include', b'include_next')
                directive = False
            if token in banned and not (token in (b'L', b'u', b'U', b'u8') and index < len(data) and data[index] in (34, 39)):
                return token.decode('ascii'), line_numbers[start]
            line_start = False
        else:
            line_start = False
            index += 1
    return None
