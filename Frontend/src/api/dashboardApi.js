import axiosClient from './axiosClient';

// batchStatus scopes the Batches Overview table only (active/draft/cancelled/all) - the stat
// cards above it describe overall state and don't change with this filter. Defaults to
// 'active' server-side when omitted.
export const getDashboardSummary = (batchStatus) =>
  axiosClient
    .get('/dashboard/', { params: batchStatus ? { batch_status: batchStatus } : {} })
    .then((r) => r.data);
