package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestTokenAuthRejectsMissingToken(t *testing.T) {
	router := NewRouter()
	router.Get(
		"/protected",
		TokenAuth(TokenAuthConfig{
			Header:  "X-Service-Token",
			Token:   "secret",
			Message: "unauthorized",
		})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			WriteJSON(w, http.StatusOK, map[string]bool{"ok": true})
		})).ServeHTTP,
	)

	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/protected", nil))

	if response.Code != http.StatusOK {
		t.Fatalf("expected transport status 200, got %d", response.Code)
	}
	if got := response.Body.String(); !strings.Contains(got, `"internal_code":40001`) {
		t.Fatalf("unexpected response body %s", got)
	}
}

func TestTokenAuthAllowsMatchingToken(t *testing.T) {
	router := NewRouter()
	router.Get(
		"/protected",
		TokenAuth(TokenAuthConfig{
			Header:  "X-Service-Token",
			Token:   "secret",
			Message: "unauthorized",
		})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			WriteJSON(w, http.StatusOK, map[string]bool{"ok": true})
		})).ServeHTTP,
	)

	request := httptest.NewRequest(http.MethodGet, "/protected", nil)
	request.Header.Set("X-Service-Token", "secret")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
}

func TestTokenAuthCanAllowEmptyConfiguredToken(t *testing.T) {
	router := NewRouter()
	router.Get(
		"/protected",
		TokenAuth(TokenAuthConfig{
			Header:          "X-Service-Token",
			Token:           "",
			Message:         "unauthorized",
			AllowEmptyToken: true,
		})(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			WriteJSON(w, http.StatusOK, map[string]bool{"ok": true})
		})).ServeHTTP,
	)

	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/protected", nil))

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
}
