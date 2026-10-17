import importlib.util, io, os, re, sys
spec = importlib.util.spec_from_file_location('hy', 'evaluation/hygiene.py')
hy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hy)

WEB = 'web'
for f in sorted(os.listdir(WEB)):
    if not f.endswith('.js'):
        continue
    src = io.open(os.path.join(WEB, f), encoding='utf-8').read()
    m = hy.parse_module(src)
    code = m['code']
    # how many times each imported name appears anywhere in the body
    used = set(hy._IDENT.findall(hy.RE_PROP.sub(' ', code))) | \
           set(hy._IDENT.findall(code))
    unused = []
    for names, target in m['imports']:
        for n in sorted(names):
            if n == '$':
                hits = len(re.findall(r'[^\w$]\$\(', code))
            else:
                hits = len(re.findall(r'(?<![\w$])' + re.escape(n) + r'(?![\w$])', code))
            if hits == 0:
                unused.append(n + ' <- ' + target)
    head = src.split('*/')[0]
    declared = set(re.findall(r'@requires\s+\./([\w.]+)\s+([^\n]*)', head))
    imported_files = {os.path.basename(t) for _, t in m['imports']}
    hdr_files = {d[0] for d in declared}
    print('== ' + f)
    if unused:
        print('   未使用的 import: ' + '; '.join(unused))
    if hdr_files - imported_files:
        print('   头部 @requires 提到了但没 import: ' + ', '.join(sorted(hdr_files - imported_files)))
    if imported_files - hdr_files:
        print('   import 了但头部没提: ' + ', '.join(sorted(imported_files - hdr_files)))
