"""Verify the exact SAT-boundary condition and its retention in the checked native micro runs."""
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("micro",type=Path)
    root=p.parse_args().micro.resolve()
    result={}
    for case,clause,expected in (("true-guard",[11,13],{"same":1,"conditional":0}),
                                 ("competition",[11,13,15],{"same":1,"add-write":1,"guard":0})):
        observations=(root/case/"oracle/native-theory.tsv").read_text().splitlines()
        assert len(observations)==1
        tag,*lits=observations[0].split()
        assert tag=="A" and list(map(int,lits))==clause
        for change,n in expected.items():
            data=dict(r.split() for r in (root/case/change/"metrics.tsv").read_text().splitlines())
            assert int(data["complete_theory_reasons"])==1 and int(data["theory_reasons_survive"])==n
        result[case]=dict(native_reason=clause,discharged_guard=7 if 15 in clause else None,survival=expected)
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
