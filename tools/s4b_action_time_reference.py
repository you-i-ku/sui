"""Independent S4b stage2/3 ruler; no imports of sui or test implementation.

--check reads the existing fixed values without rewriting them. The phase
and mixed receipt-law values are mathematical fixtures; a public binding for
continuous receipts and the phase root anchor must be specified separately.
"""
import argparse
from fractions import Fraction as F
import json
import math
from pathlib import Path


def serial(value):
    if isinstance(value, F):
        return [value.numerator, value.denominator]
    if isinstance(value, dict):
        return {key: serial(v) for key, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    return value


def entropy(probabilities):
    return -math.fsum(float(p)*math.log(float(p)) for p in probabilities if p)


def waiting_joint(correlated):
    # Tick phase0, threshold11, arrivals10.25/10.75 both before11.
    # Survive in state0 until12 with probability2^(-4*(12-tau)).
    mass = {"00": F(), "01": F(), "11": F()}
    for state in (0, 1):
        delays = ((F(1, 4) if state == 0 else F(3, 4), F(1)),) if correlated else (
            (F(1, 4), F(1, 2)), (F(3, 4), F(1, 2)))
        for delta, weight in delays:
            survival = F(1, 2**int(4*(1-delta))) if state == 0 else F(0)
            if state == 0:
                mass["00"] += weight*survival/2
                mass["01"] += weight*(1-survival)/2
            else:
                mass["11"] += weight/2
    return mass


def values():
    # C_phi(3/4)=floor(3/4-phi)=0 in both worlds; b_1=1+phi.
    phases = (F(0), F(1, 2))
    boundaries = tuple(1+p for p in phases)
    phase_probability = sum((F(1, 2) for b in boundaries if b <= F(5, 4)), F())
    assert tuple(math.floor(F(3, 4)-p) for p in phases) == (0, 0)
    # tau=max(1/2,T_in), T_in uniform[0,1], Delta=0. Half the
    # receipt interval collapses onto the boundary; the rest has Jacobian1.
    mixed = {"atom_time_s": F(1, 2), "atom_mass": F(1, 2),
        "density_interval_s": (F(1, 2), F(1)), "density_per_s": F(1),
        "continuous_mass": F(1, 2), "mean_s": F(5, 8), "second_s2": F(5, 12),
        "cdf_at_3_4": F(3, 4)}
    return {"T10_at_half": 1-2**(-.5), "T10_at_one": F(1, 2),
        "T11_completion_s": F(1, 2)+(2-F(1, 2))/2,
        "T17_joint": waiting_joint(False), "T21_joint": waiting_joint(True),
        "T18_read_information": entropy((F(5, 16), F(11, 16))),
        "T19_dispatch_s": tuple(max(F(1), F(1, 4)+2*u) for u in (0, 1)),
        "phase": {"boundaries_s": boundaries, "state1_at_5_4": phase_probability,
                  "wrong_representative_boundary": F(1)}, "continuous_receipt": mixed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    result = values()
    assert result["T11_completion_s"] == F(5, 4)
    assert result["phase"]["state1_at_5_4"] == F(1, 2)
    assert sum(result["T17_joint"].values()) == sum(result["T21_joint"].values()) == 1
    mixed = result["continuous_receipt"]
    assert mixed["atom_mass"]+mixed["continuous_mass"] == 1
    # Analytic pushforward moments integrate over RECEIPT time, independently
    # of the resulting atom/density description above.
    for n, key in ((1, "mean_s"), (2, "second_s2")):
        integral = F(1, 2)**(n+1)+(1-F(1, 2)**(n+1))/(n+1)
        assert integral == mixed[key]
    if args.check:
        frozen = json.loads(args.check.read_bytes())["items"]
        for item in ("T17", "T21"):
            assert serial(result[item+"_joint"]) == frozen[item]["values"]["joint_U_Z"]
        assert serial(result["T11_completion_s"]) == frozen["T11"]["values"]["completion_s"]
        assert abs(result["T18_read_information"]-frozen["T18"]["values"]["read_increment"]) < 1e-14
    print("PASS: independent finite waiting tables, progress, phase, mixed receipt pushforward")
    print(json.dumps(serial(result), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
