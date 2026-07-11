package route_policy

import "testing"

func TestDefaultRoutePolicyClassifiesLocalHealth(t *testing.T) {
	policy := NewDefaultRoutePolicy("http://backend.local")

	route := policy.Resolve("/health")

	if !route.Public || route.AuthRequired || !route.LocalHealth {
		t.Fatalf("health route = %#v, want public local health", route)
	}
	if route.UpstreamService != "" || route.UpstreamAddr != "" {
		t.Fatalf("health route should not have upstream: %#v", route)
	}
}

func TestDefaultRoutePolicyClassifiesPublicHealthUpstream(t *testing.T) {
	policy := NewDefaultRoutePolicy("http://backend.local")

	route := policy.Resolve("/health/live")

	if !route.Public || route.AuthRequired || route.LocalHealth {
		t.Fatalf("public upstream route = %#v", route)
	}
	if route.UpstreamService != "monkeyocr-backend" || route.UpstreamAddr != "http://backend.local" {
		t.Fatalf("public upstream target = %#v", route)
	}
}

func TestDefaultRoutePolicyProtectsUnknownAPIPaths(t *testing.T) {
	policy := NewDefaultRoutePolicy("http://backend.local")

	route := policy.Resolve("/v1/jobs")

	if route.Public || !route.AuthRequired || route.LocalHealth {
		t.Fatalf("protected route = %#v", route)
	}
}
