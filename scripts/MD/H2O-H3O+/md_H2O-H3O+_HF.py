from pyscf import gto, md

from pyscf.scf import hf

import numpy as np


def get_mol(geometry):
    mol = gto.Mole()

    mol.build(
        atom=[
            ("O", geometry[0]),
            ("H", geometry[1]),
            ("H", geometry[2]),
            ("H", geometry[3]),
            ("O", geometry[4]),
            ("H", geometry[5]),
            ("H", geometry[6]),
        ],
        basis="6-31G",
        symmetry=False,
        unit="Bohr",
        charge=1,
    )

    return mol


stretch_factor = 1.5
init_geometry = stretch_factor * np.array(
    [
        [0.0000000, 0.0000000, 0.0000000],
        [-0.6237519, -0.9109667, -1.4354514],
        [-0.6237519, -0.9109667, 1.4354514],
        [5.5028821 / 2, 0.0, 0.0],
        [5.5028821, 0.0000000, 0.0000000],
        [3.6897611, 0.1745837, 0.0000000],
        [6.1311264, 1.6956360, 0.0000000],
    ]
)

mol = get_mol(init_geometry)


init_mol = mol.copy()

mf = init_mol.RHF()

steps = 300
dt = 5

scanner_fun = mf.nuc_grad_method().as_scanner()

open("dipole_moment_HF.txt", "w").close()


def callback(locals):
    mol = locals["mol"]
    hf_obj = locals["scanner"].base

    one_rdm = hf_obj.make_rdm1()
    dipole_moment = hf.dip_moment(mol, one_rdm)

    with open("dipole_moment_HF.txt", "a") as fl:
        for el in dipole_moment:
            fl.write("{}  ".format(el))
        fl.write("\n")


frames = []
scanner_fun.mol = init_mol.copy()
myintegrator = md.NVE(
    scanner_fun,
    steps=steps,
    dt=dt,
    incore_anyway=True,
    frames=frames,
    veloc=None,
    trajectory_output="HF_trajectory.xyz",
    energy_output="HF_energy.xyz",
)
myintegrator.run()


np.save("traj_HF.npy", np.array([frame.coord for frame in frames]))