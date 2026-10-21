import axiosClient from './axiosClient';

// Returns the paginated envelope {count, next, previous, results} - pass `page` to move
// between pages.
// `status` is one of invited | active | deactivated - the same three the Status column shows.
// Omitted or blank means every user (see views/users.STATUS_FILTERS).
export const listUsers = ({ page, status } = {}) => {
  const params = {};
  if (page) params.page = page;
  if (status) params.status = status;
  return axiosClient.get('/users/', { params }).then((r) => r.data);
};

export const getUser = (id) => axiosClient.get(`/users/${id}/`).then((r) => r.data);

export const createUser = (payload) => axiosClient.post('/users/', payload).then((r) => r.data);

export const updateUser = (id, payload) =>
  axiosClient.patch(`/users/${id}/`, payload).then((r) => r.data);

// Deactivation, not deletion - the row is preserved and the account is flipped to Inactive.
// The DELETE verb is kept because that's the existing route; the backend never removes the row.
export const deactivateUser = (id) => axiosClient.delete(`/users/${id}/`).then((r) => r.data);
