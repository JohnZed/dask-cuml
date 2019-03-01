# Copyright (c) 2019, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from sklearn.neighbors import NearestNeighbors

from dask.distributed import Client, wait
from dask_cuda import LocalCUDACluster

def test_end_to_end():

    cluster = LocalCUDACluster(threads_per_worker=1)
    client = Client(cluster)

    # NOTE: The LocalCUDACluster needs to be started before any imports that
    # could potentially create a CUDA context.

    import dask_cudf

    import cudf
    import numpy as np

    from dask_cuml.neighbors import NearestNeighbors as cumlKNN

    def create_df(f, m, n):
        X = np.random.rand(m, n)
        ret = cudf.DataFrame([(i, X[:, i].astype(np.float32)) for i in range(n)],
                             index=cudf.dataframe.RangeIndex(f * m, f * m + m, 1))
        return ret

    def get_meta(df):
        ret = df.iloc[:0]
        return ret

    # Per gpu/worker
    train_m = 500
    train_n = 25

    search_m = 10
    search_k = 15

    workers = client.has_what().keys()

    # Create dfs on each worker (gpu)
    dfs = [client.submit(create_df, n, train_m, train_n, workers=[worker])
           for worker, n in list(zip(workers, list(range(len(workers)))))]

    # Wait for completion
    wait(dfs)

    meta = client.submit(get_meta, dfs[0]).result()

    X_df = dask_cudf.from_delayed(dfs, meta=meta)
    X_pd = X_df.compute().to_pandas()

    cumlNN = cumlKNN()
    cumlNN.fit(X_df)

    sklNN = NearestNeighbors(metric = "sqeuclidean")
    sklNN.fit(X_pd)

    cuml_D, cuml_I = cumlNN.kneighbors(X_df[0:search_m-1], search_k)
    sk_D, sk_I = sklNN.kneighbors(X_pd[0:search_m], search_k)

    cuml_I_nd = np.array(cuml_I.compute().as_gpu_matrix(), dtype = sk_I.dtype)
    cuml_D_nd = np.array(cuml_D.compute().as_gpu_matrix(), dtype = sk_D.dtype)

    print(str(cuml_D_nd.dtype))
    print(str(sk_D.dtype))

    assert np.array_equal(cuml_I_nd, sk_I)
    assert np.allclose(cuml_D_nd, sk_D, atol = 1e-5)

    cluster.close()