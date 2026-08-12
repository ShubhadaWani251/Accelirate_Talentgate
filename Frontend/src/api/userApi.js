import axiosClient from './axiosClient';

// Returns the paginated envelope {count, next, previous, results} - pass `page` to move
// between pages.
export const listUsers = ({ page } = {}) => {
  const params = {};
  if (page) params.page = page;
  return axiosClient.get('/users/', { params }).then((r) => r.data);
};

export const getUser = (id) => axiosClient.get(`/users/${id}/`).then((r) => r.data);

export const createUser = (payload) => axiosClient.post('/users/', payload).then((r) => r.data);

export const updateUser = (id, payload) =>
  axiosClient.patch(`/users/${id}/`, payload).then((r) => r.data);

export const deleteUser = (id) => axiosClient.delete(`/users/${id}/`).then((r) => r.data);
