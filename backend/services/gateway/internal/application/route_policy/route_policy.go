package route_policy

import "strings"

var PublicExactPaths = []string{
	"/health",
	"/health/live",
	"/health/ready",
	"/openapi.json",
}

var PublicPathPrefixes = []string{}

// Route describes how the gateway should handle one request path.
type Route struct {
	Public          bool
	AuthRequired    bool
	LocalHealth     bool
	UpstreamService string
	UpstreamAddr    string
}

// RoutePolicy classifies request paths into local and upstream gateway behavior.
type RoutePolicy struct {
	backendURL string
}

// NewDefaultRoutePolicy returns the MonkeyOCR backend route policy.
func NewDefaultRoutePolicy(backendURL string) RoutePolicy {
	return RoutePolicy{backendURL: backendURL}
}

// Resolve returns the route behavior for a request path.
func (policy RoutePolicy) Resolve(path string) Route {
	if path == "/health" {
		return Route{Public: true, LocalHealth: true}
	}

	public := isPublicPath(path)
	return Route{
		Public:          public,
		AuthRequired:    !public,
		UpstreamService: "monkeyocr-backend",
		UpstreamAddr:    policy.backendURL,
	}
}

func isPublicPath(path string) bool {
	for _, exact := range PublicExactPaths {
		if path == exact {
			return true
		}
	}
	for _, prefix := range PublicPathPrefixes {
		if strings.HasPrefix(path, prefix) {
			return true
		}
	}
	return false
}
