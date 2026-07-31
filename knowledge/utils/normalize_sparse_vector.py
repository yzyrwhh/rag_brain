import numpy as np


def normalize_sparse_vector(sparse_vec):

    if not sparse_vec:  # 空向量直接返回
        return sparse_vec
    values = np.array(list(sparse_vec.values()), dtype=np.float64)

    l2_norm = np.linalg.norm(values)
    if l2_norm < 1e-9:  # 范数接近 0 时，直接返回原向量
        return sparse_vec

    normalized_values = values / l2_norm

    return dict(zip(sparse_vec.keys(), normalized_values))