package deps

import "net/http"

// UpstreamProxy forwards a request to the selected upstream service.
type UpstreamProxy interface {
	ServeHTTP(http.ResponseWriter, *http.Request, string)
}
