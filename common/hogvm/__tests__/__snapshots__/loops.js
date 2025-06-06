function values (obj) { if (typeof obj === 'object' && obj !== null) { if (Array.isArray(obj)) { return [...obj] } else if (obj instanceof Map) { return Array.from(obj.values()) } return Object.values(obj) } return [] }
function tuple (...args) { const tuple = args.slice(); tuple.__isHogTuple = true; return tuple; }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function keys (obj) { if (typeof obj === 'object' && obj !== null) { if (Array.isArray(obj)) { return Array.from(obj.keys()) } else if (obj instanceof Map) { return Array.from(obj.keys()) } return Object.keys(obj) } return [] }
function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
function __printHogValue(obj, marked = new Set()) {
    if (typeof obj === 'object' && obj !== null && obj !== undefined) {
        if (marked.has(obj) && !__isHogDateTime(obj) && !__isHogDate(obj) && !__isHogError(obj)) { return 'null'; }
        marked.add(obj);
        try {
            if (Array.isArray(obj)) {
                if (obj.__isHogTuple) { return obj.length < 2 ? `tuple(${obj.map((o) => __printHogValue(o, marked)).join(', ')})` : `(${obj.map((o) => __printHogValue(o, marked)).join(', ')})`; }
                return `[${obj.map((o) => __printHogValue(o, marked)).join(', ')}]`;
            }
            if (__isHogDateTime(obj)) { const millis = String(obj.dt); return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${__escapeString(obj.zone)})`; }
            if (__isHogDate(obj)) return `Date(${obj.year}, ${obj.month}, ${obj.day})`;
            if (__isHogError(obj)) { return `${String(obj.type)}(${__escapeString(obj.message)}${obj.payload ? `, ${__printHogValue(obj.payload, marked)}` : ''})`; }
            if (obj instanceof Map) { return `{${Array.from(obj.entries()).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`; }
            return `{${Object.entries(obj).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`;
        } finally {
            marked.delete(obj);
        }
    } else if (typeof obj === 'boolean') return obj ? 'true' : 'false';
    else if (obj === null || obj === undefined) return 'null';
    else if (typeof obj === 'string') return __escapeString(obj);
            if (typeof obj === 'function') return `fn<${__escapeIdentifier(obj.name || 'lambda')}(${obj.length})>`;
    return obj.toString();
}
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __escapeString(value) {
    const singlequoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', "'": "\\'" }
    return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
}
function __escapeIdentifier(identifier) {
    const backquoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', '`': '\\`' }
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\``;
}

print("-- test while loop --");
{
    let i = 0;
    while ((i < 3)) {
            i = (i + 1)
            print(i);
        }
    print(i);
}
print("-- test for loop --");
{
    for (let i = 0; (i < 3); i = (i + 1)) {
            print(i);
        }
}
print("-- test emptier for loop --");
{
    let i = 0;
    for (; (i < 3); ) {
            print("woo");
            i = (i + 1)
        }
    print("hoo");
}
print("-- for in loop with arrays --");
{
    let arr = [1, 2, 3];
    for (let i of values(arr)) {
            print(i);
        }
}
print("-- for in loop with arrays and keys --");
{
    let arr = [1, 2, 3];
    for (let k of keys(arr)) { let v = arr[k]; {
            print(k, v);
        } }
}
print("-- for in loop with tuples --");
{
    let tup = tuple(1, 2, 3);
    for (let i of values(tup)) {
            print(i);
        }
}
print("-- for in loop with tuples and keys --");
{
    let tup = tuple(1, 2, 3);
    for (let k of keys(tup)) { let v = tup[k]; {
            print(k, v);
        } }
}
print("-- for in loop with dicts --");
{
    let obj = {"first": "v1", "second": "v2", "third": "v3"};
    for (let i of values(obj)) {
            print(i);
        }
}
print("-- for in loop with dicts and keys --");
{
    let obj = {"first": "v1", "second": "v2", "third": "v3"};
    for (let k of keys(obj)) { let v = obj[k]; {
            print(k, v);
        } }
}
