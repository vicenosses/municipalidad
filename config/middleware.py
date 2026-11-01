from django.utils.cache import patch_cache_control


class PaginasPrivadasSinCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, 'user', None) and request.user.is_authenticated:
            patch_cache_control(response, private=True, no_store=True, no_cache=True, must_revalidate=True)
        return response
