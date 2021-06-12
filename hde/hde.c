#include "general.h"
#include "SparseMatrix.h"
#include "power.h"

void get_CCT(int n, int K, real *dist, real **CCT){
  /*
    Input:
    dist: of dimension k*n, dist[k*n: (k+1)*n) gives the distance of every node to the k-th center.
    Output:
    CCT: dist*dist^T
    return: flag. if not zero, the graph is not connected, or out of memory.
  */
  int i, j, k;

  if (!(*CCT)) *CCT = MALLOC(sizeof(real)*K*K);

  for (i = 0; i < K; i++){
    for (j = 0; j <= i; j++){
      (*CCT)[i*K+j] = 0;
      for (k = 0; k < n; k++){
	(*CCT)[i*K+j] += dist[n*i+k]*dist[n*j+k];
      }
    }
  }
  for (i = 0; i < K; i++){
    for (j = i+1; j < K; j++){
      (*CCT)[i*K+j] = (*CCT)[j*K+i];
    }
  }


}
void hde(int dim, SparseMatrix D, int K, real *x, int *centers_user, int *flag){
  int *centers = NULL;
  real *dist = NULL;
  int weighted = TRUE;
  int root = 0;
  int centering = TRUE;
  int n = D->m;
  real *CCT = NULL;/* the matrix C*C^T, where C is a Kxn matrix of distances */
  int random_seed = 123;
  int maxit = 200;
  real tol = 0.0001;
  real *eigv = NULL, *eigs = NULL;
  int transpose = TRUE;
  int i, j;
  real *v;

  K = MAX(0, MIN(K, D->m));

  if (!centers_user){
    SparseMatrix_k_centers(D, weighted, K, root, &centers, centering, &dist);
  } else {
    SparseMatrix_k_centers_user(D, weighted, K, centers_user, centering, &dist);
  }
  
  get_CCT(n, K, dist, &CCT); 

  power_method(matvec_dense,
	       (void*) CCT, K, dim, random_seed, maxit, tol, &eigv, &eigs);

  v = MALLOC(sizeof(real)*n);

  for (i = 0; i < dim; i++){
    matvec_dense((void*) dist, K, n, &(eigv[i*K]), &v, transpose, flag);
    assert(!(*flag));
    for (j = 0; j < n; j++) {
      x[j*dim + i] = v[j];
    }
  }
  FREE(v);
  if (centers) FREE(centers);
  FREE(dist);
  FREE(eigv);
  FREE(eigs);

  return;
} 
