package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
)

// Router is the Chi mux type used by service entrypoints.
type Router = chi.Mux

// NewRouter returns a Chi router with no request logger.
func NewRouter() *Router {
	router := chi.NewRouter()
	router.Use(RequestID)
	router.Use(Recovery)
	router.NotFound(func(w http.ResponseWriter, r *http.Request) {
		WriteBusinessError(w, InternalStatusCommonResourceNotFound, "接口不存在", "route_not_found")
	})
	router.MethodNotAllowed(func(w http.ResponseWriter, r *http.Request) {
		WriteBusinessError(w, InternalStatusCommonInvalidArgument, "请求方法不受支持", "method_not_allowed")
	})
	return router
}
