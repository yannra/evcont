import numpy as np

from pyscf import scf, ao2mo, grad

from EVCont.ab_initio_eigenvector_continuation import approximate_ground_state

from EVCont.electron_integral_utils import get_loewdin_trafo


def get_overlap_grad(mol):
    inner_deriv = mol.intor("int1e_ipovlp", comp=3)

    deriv = np.zeros((3, mol.natm, mol.nao, mol.nao))
    for i in range(mol.natm):
        _, _, x, y = mol.aoslice_by_atom()[i]
        deriv[:, i, x:y, :] -= inner_deriv[:, x:y, :]

    deriv = deriv + deriv.transpose(0, 1, 3, 2)

    return np.transpose(deriv, (2, 3, 1, 0))


def loewdin_trafo_grad(overlap_mat):
    vals, vecs = np.linalg.eigh(overlap_mat)
    vals = np.array(vals)
    vecs = np.array(vecs)

    rounded_vals = np.round(vals, decimals=5)
    degenerate_vals = np.unique(rounded_vals)

    U_full = np.zeros((*overlap_mat.shape, *overlap_mat.shape))
    degenerate_subspace = np.zeros(overlap_mat.shape, dtype=bool)

    # Take care of degeneracies
    for val in degenerate_vals:
        degenerate_ids = (np.argwhere(rounded_vals == val)).flatten()
        subspace = vecs[:, degenerate_ids]

        V_projected = 0.5 * np.einsum(
            "ai,bj->abij", subspace, subspace
        ) + 0.5 * np.einsum("bi,aj->abij", subspace, subspace)

        # Get rotation to diagonalise V in degenerate subspace
        _, U = np.linalg.eigh(V_projected)
        U = np.array(U)
        U_full[
            np.ix_(
                np.ones(U_full.shape[0], dtype=bool),
                np.ones(U_full.shape[1], dtype=bool),
                degenerate_ids,
                degenerate_ids,
            )
        ] = U
        degenerate_subspace[np.ix_(degenerate_ids, degenerate_ids)] = True

    vecs_rotated = np.einsum("ij,abjk->abik", vecs, U_full)

    Vji = 0.5 * np.einsum(
        "abai,abbj->abij", vecs_rotated, vecs_rotated
    ) + 0.5 * np.einsum("abbi,abaj->abij", vecs_rotated, vecs_rotated)

    Zji = np.zeros((*overlap_mat.shape, *overlap_mat.shape))
    Zji[:, :, ~degenerate_subspace] = Vji[:, :, ~degenerate_subspace] / (
        (vals - np.expand_dims(vals, -1))[~degenerate_subspace]
    )

    dvecs = np.einsum("abij,abjk->abik", vecs_rotated, Zji)
    dvals = Vji[:, :, np.arange(Vji.shape[2]), np.arange(Vji.shape[3])]

    transformed_vals = np.where(vals > 1.0e-15, 1 / np.sqrt(vals), 0.0)
    d_transformed_vals = (
        np.where(vals > 1.0e-15, -(0.5 / np.sqrt(vals) ** 3), 0.0) * dvals
    )
    dS = (
        np.einsum("abij, abkj->abik", dvecs * transformed_vals, vecs_rotated)
        + np.einsum(
            "abij, abkj->abik",
            vecs_rotated * np.expand_dims(d_transformed_vals, axis=-2),
            vecs_rotated,
        )
        + np.einsum("abij, abkj->abik", vecs_rotated * transformed_vals, dvecs)
    )
    return np.transpose(dS, (2, 3, 0, 1))


def get_derivative_ao_mo_trafo(mol):
    overlap_grad = get_overlap_grad(mol)
    trafo_grad = np.einsum(
        "ijkl, ijmn->klmn",
        np.array(loewdin_trafo_grad(mol.intor("int1e_ovlp")), dtype=float),
        overlap_grad,
    )

    return trafo_grad


def get_one_el_grad_ao(mol):
    hcore_gen = grad.RHF(scf.RHF(mol)).hcore_generator()
    return_val = np.array([hcore_gen(i) for i in range(mol.natm)])
    return np.transpose(return_val, (2, 3, 0, 1))


def get_one_el_grad(mol, ao_mo_trafo=None, ao_mo_trafo_grad=None):
    if ao_mo_trafo is None:
        ao_mo_trafo = np.array(
            get_loewdin_trafo(np.array(mol.intor("int1e_ovlp"))), dtype=float
        )

    h1_ao = scf.hf.get_hcore(mol)

    if ao_mo_trafo_grad is None:
        ao_mo_trafo_grad = get_derivative_ao_mo_trafo(mol)

    h1_grad_ao = get_one_el_grad_ao(mol)

    h1_grad = np.einsum(
        "ijkl,im,mn->jnkl", ao_mo_trafo_grad, h1_ao, ao_mo_trafo, optimize="optimal"
    )

    h1_grad += np.swapaxes(h1_grad, 0, 1)

    h1_grad += np.einsum(
        "ij,iklm,kn->jnlm", ao_mo_trafo, h1_grad_ao, ao_mo_trafo, optimize="optimal"
    )

    return h1_grad


def get_two_el_grad_ao(mol):
    inner_deriv = mol.intor("int2e_ip1", comp=3)

    deriv = np.zeros((3, mol.natm, mol.nao, mol.nao, mol.nao, mol.nao))
    for i in range(mol.natm):
        _, _, x, y = mol.aoslice_by_atom()[i]
        deriv[:, i, x:y, :, :, :] -= inner_deriv[:, x:y]

    deriv = (
        deriv
        + deriv.transpose(0, 1, 3, 2, 5, 4)
        + deriv.transpose(0, 1, 4, 5, 2, 3)
        + deriv.transpose(0, 1, 5, 4, 3, 2)
    )

    return np.transpose(deriv, (2, 3, 4, 5, 1, 0))


def get_two_el_grad(mol, ao_mo_trafo=None, ao_mo_trafo_grad=None):
    if ao_mo_trafo is None:
        ao_mo_trafo = np.array(
            get_loewdin_trafo(np.array(mol.intor("int1e_ovlp"))), dtype=float
        )

    h2_ao = mol.intor("int2e")

    if ao_mo_trafo_grad is None:
        ao_mo_trafo_grad = get_derivative_ao_mo_trafo(mol)

    h2_grad_ao = np.array(get_two_el_grad_ao(mol))

    h2_grad = np.einsum(
        "abcd,aimn,bj,ck,dl->ijklmn",
        h2_ao,
        ao_mo_trafo_grad,
        ao_mo_trafo,
        ao_mo_trafo,
        ao_mo_trafo,
        optimize="optimal",
    )

    # TODO: This can certainly be done faster via appropriate transpose operations
    h2_grad += np.einsum(
        "abcd,ai,bjmn,ck,dl->ijklmn",
        h2_ao,
        ao_mo_trafo,
        ao_mo_trafo_grad,
        ao_mo_trafo,
        ao_mo_trafo,
        optimize="optimal",
    )
    h2_grad += np.einsum(
        "abcd,ai,bj,ckmn,dl->ijklmn",
        h2_ao,
        ao_mo_trafo,
        ao_mo_trafo,
        ao_mo_trafo_grad,
        ao_mo_trafo,
        optimize="optimal",
    )
    h2_grad += np.einsum(
        "abcd,ai,bj,ck,dlmn->ijklmn",
        h2_ao,
        ao_mo_trafo,
        ao_mo_trafo,
        ao_mo_trafo,
        ao_mo_trafo_grad,
        optimize="optimal",
    )

    h2_grad += np.einsum(
        "abcdmn,ai,bj,ck,dl->ijklmn",
        h2_grad_ao,
        ao_mo_trafo,
        ao_mo_trafo,
        ao_mo_trafo,
        ao_mo_trafo,
        optimize="optimal",
    )

    return h2_grad


def get_energy_with_grad(mol, one_RDM, two_RDM, S, hermitian=True):
    # Construct h1 and h2
    ao_mo_trafo = np.array(
        get_loewdin_trafo(np.array(mol.intor("int1e_ovlp"))), dtype=float
    )
    ao_mo_trafo_grad = get_derivative_ao_mo_trafo(mol)

    h1 = np.linalg.multi_dot((ao_mo_trafo.T, scf.hf.get_hcore(mol), ao_mo_trafo))
    h2 = ao2mo.restore(1, ao2mo.kernel(mol, ao_mo_trafo), mol.nao)

    h1_jac = get_one_el_grad(
        mol, ao_mo_trafo=ao_mo_trafo, ao_mo_trafo_grad=ao_mo_trafo_grad
    )

    h2_jac = get_two_el_grad(
        mol, ao_mo_trafo=ao_mo_trafo, ao_mo_trafo_grad=ao_mo_trafo_grad
    )

    en, vec = approximate_ground_state(h1, h2, one_RDM, two_RDM, S, hermitian=hermitian)

    one_rdm_predicted = np.array(np.einsum("i,ijkl,j->kl", vec, one_RDM, vec))
    two_rdm_predicted = np.array(np.einsum("i,ijklmn,j->kl", vec, two_RDM, vec))

    jac_H = np.sum(
        np.expand_dims(one_rdm_predicted, (-1, -2)) * h1_jac, axis=(-3, -4)
    ) + 0.5 * np.sum(
        np.expand_dims(two_rdm_predicted, (-1, -2)) * h2_jac, axis=(-3, -4, -5, -6)
    )

    return (
        en.real + mol.energy_nuc(),
        np.array(jac_H + grad.RHF(scf.RHF(mol)).grad_nuc()),
    )