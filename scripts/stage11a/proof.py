"""Local proof replay for retained OC facts. No saturation or order-search calls."""


def replay(branch, pair, proof, accepted, rules):
    a,b=pair
    if a not in branch.on or b not in branch.on or not proof.leaves <= branch.available:
        return False
    if not ({rules} | branch.endpoints(a,b)) <= proof.local:
        return False
    if any(p not in accepted for p in proof.parents):
        return False
    if proof.leaves != proof.local.union(*(accepted[p].leaves for p in proof.parents)):
        return False

    def choice(w,r):
        terms={("select",w,r),("decl-rf",w,r)} | branch.endpoints(r)
        if not w.startswith("init:"):
            terms |= branch.endpoints(w)
        return (w,r) in branch.selected and terms <= proof.local

    if proof.rule=="static projection" and not proof.parents:
        # Find a nonempty path using only this record's authenticated typed leaves.
        adj={}
        for item in proof.local:
            if item[0] in ("po","apo"):
                _,x,y=item
                if {branch.signature[x],branch.signature[y]} <= proof.local:
                    adj.setdefault(x,set()).add(y)
        reachable=set()
        todo=list(adj.get(a,()))
        for node in todo:
            if node==b: return True
            if node not in reachable:
                reachable.add(node)
                todo.extend(adj.get(node,()))
        return False
    if proof.rule=="read from" and not proof.parents:
        return choice(a,b)
    if proof.rule=="initial read" and not proof.parents:
        return (branch.by[b].op=="W" and branch.by[a].addr==branch.by[b].addr
                and choice("init:"+branch.by[a].addr,a))
    if proof.rule=="transitive" and len(proof.parents)==2:
        (x,y),(z,t)=proof.parents
        return (x,t)==(a,b) and y==z
    if len(proof.parents)!=1:
        return False
    x,y=proof.parents[0]
    if proof.rule=="block lift":
        return (branch.groups[x]!=branch.groups[y] and a in branch.groups[x] and b in branch.groups[y]
                and {branch.membership[x],branch.membership[y]} <= proof.local)
    if proof.rule=="from read":
        return (y==b and x!=b and branch.by[b].op=="W" and branch.by[x].addr==branch.by[b].addr
                and choice(x,a))
    if proof.rule=="write serialization":
        return (x==a and a!=b and branch.by[a].op=="W" and branch.by[a].addr==branch.by[b].addr
                and choice(b,y))
    return False
