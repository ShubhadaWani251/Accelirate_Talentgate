from rest_framework.pagination import PageNumberPagination


class StandardResultsPagination(PageNumberPagination):
    """Shared page size across list endpoints that return PII (candidates, batches) - without
    this, CandidateListView/BatchListCreateView return every matching row in one response,
    which gets slower and exposes more PII per-request as the dataset grows.
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
