#include "general.h"
#include "SparseMatrix.h"
#include "power.h"
#include "hde.h"
#include "pivot_mds.h"

static void square_double_centering(real *dist, int m, int n){
  real *rowsum;
  real *colsum;
  real allsum = 0;
  int i, j;
  rowsum = MALLOC(sizeof(real)*m);/* sum of each element in row i is rowsum[i] */
  colsum = MALLOC(sizeof(real)*n);
  for (i = 0; i < m; i++) rowsum[i] = 0.;
  for (i = 0; i < n; i++) colsum[i] = 0.;

  for (i = 0; i < m; i++){
    for (j = 0; j < n; j++){
      dist[i*n+j] = dist[i*n+j]*dist[i*n+j];
      rowsum[i] += dist[i*n+j];
      colsum[j] += dist[i*n+j];
    }
  }

  for (i = 0; i < m; i++) {
    allsum += rowsum[i];
    rowsum[i] /= n;
  }
  for (i = 0; i < n; i++) {
    colsum[i] /= m;
  }
  allsum = allsum/(m*n);

  for (i = 0; i < m; i++){
    for (j = 0; j < n; j++){
      dist[i*n+j] = -0.5*(dist[i*n+j] - rowsum[i] - colsum[j] + allsum);
    }
  }

  FREE(rowsum);
  FREE(colsum);
}

void pivot_mds(int dim, SparseMatrix D, int K, real *x, int *centers_user, int *flag){
  int *centers = NULL;
  real *dist = NULL;
  int weighted = TRUE;
  int root = 0;
  int centering = FALSE;
  int n = D->m;
  real *CCT = NULL;/* the matrix C*C^T, where C is a Kxn matrix of distances */
  int random_seed = 123;
  int maxit = 200;
  real tol = 0.0001;
  real *eigv = NULL, *eigs = NULL;
  int transpose = TRUE;
  int i, j;
  real *v, vnorm;
  real scaling;

  K = MAX(0, MIN(K, D->m));

  if (!centers_user){
    SparseMatrix_k_centers(D, weighted, K, root, &centers, centering, &dist);
  } else {
    SparseMatrix_k_centers_user(D, weighted, K, centers_user, centering, &dist);
  }
  square_double_centering(dist, K, D->m);
  
  get_CCT(n, K, dist, &CCT); 
  power_method(matvec_dense,
	       (void*) CCT, K, dim, random_seed, maxit, tol, &eigv, &eigs);

  v = MALLOC(sizeof(real)*n);

  for (i = 0; i < dim; i++){
    fprintf(stderr,"eigs[%d]=%f\n",i,eigs[i]);
    matvec_dense((void*) dist, K, n, &(eigv[i*K]), &v, transpose, flag);
    assert(!(*flag));
    scaling = sqrt(sqrt(eigs[i]));/* because C*C^T approximates B^2
				     where B is the matrix of double centered
				     matrix, sqrt(sqrt(lambda))
				     is roughly sqrt(lambda_of_B) */
    vnorm = 0;
    for (j = 0; j < n; j++) {
      vnorm += v[j]*v[j];
    }
    vnorm = sqrt(vnorm);
    if (vnorm > 0) scaling /= vnorm;

    for (j = 0; j < n; j++) {
      assert(eigs[i] >= 0);
      x[j*dim + i] = scaling*v[j];
    }
  }

  FREE(v);
  if (centers) FREE(centers);
  FREE(dist);
  FREE(eigv);
  FREE(eigs);
  return;
} 
