import sys
d=open(sys.argv[1],'rb').read()
def leb(p):
    r=s=0
    while True:
        b=d[p];p+=1;r|=(b&0x7f)<<s;s+=7
        if b<0x80:return r,p
def name(p):
    n,p=leb(p);return d[p:p+n].decode('utf8','replace'),p+n
p=8;secs={}
imports=[];exports=[];simd=0;atomics=0
while p<len(d):
    sid=d[p];p+=1;sz,p=leb(p);start=p
    secs.setdefault(sid,0);secs[sid]+=sz
    if sid==0:
        nm,_=name(p);print('custom section',nm,sz)
    if sid==2:
        n,q=leb(p)
        for _ in range(n):
            m,q=name(q);f,q=name(q);k=d[q];q+=1
            if k==0: _,q=leb(q)
            elif k==1: q+=1;fl=d[q];q+=1;_,q=leb(q);q= leb(q)[1] if fl&1 else q
            elif k==2:
                fl=d[q];q+=1;mn,q=leb(q);mx=None
                if fl&1: mx,q=leb(q)
                print('import memory',m,f,'flags',fl,'min pages',mn,'max',mx)
            elif k==3: q+=2
            imports.append((m,f,k))
    if sid==5:
        n,q=leb(p);fl=d[q];q+=1;mn,q=leb(q);mx=None
        if fl&1: mx,q=leb(q)
        print('memory flags',fl,'min pages',mn,'(',mn*64/1024,'MB) max',mx, '' if mx is None else f'({mx*64/1024} MB)')
    if sid==7:
        n,q=leb(p)
        for _ in range(n):
            f,q=name(q);k=d[q];q+=1;_,q=leb(q);exports.append(f)
    if sid==10:
        body=d[p:p+sz];simd=body.count(b'\xfd');atomics=body.count(b'\xfe')
    p=start+sz
print('sections',{k:v for k,v in secs.items()})
print('imports',len(imports),'funcs', sum(1 for i in imports if i[2]==0))
print('exports',len(exports)); print(sorted(e for e in exports if not e.startswith('dynCall'))[:200])
print('0xfd(simd-prefix) bytes in code (rough)',simd,'0xfe(atomics) bytes',atomics)
