import axiosClient from './axiosClient';

export const getDashboardSummary = () => axiosClient.get('/dashboard/').then((r) => r.data);
