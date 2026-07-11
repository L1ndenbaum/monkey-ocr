package api

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDecodeJSONReadsBoundedRequestBody(t *testing.T) {
	router := NewRouter()
	router.Post("/decode", func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			Name string `json:"name"`
		}
		if !DecodeJSON(w, r, &request, 1024) {
			return
		}
		WriteJSON(w, http.StatusOK, map[string]string{"name": request.Name})
	})

	response := httptest.NewRecorder()
	router.ServeHTTP(
		response,
		httptest.NewRequest(http.MethodPost, "/decode", strings.NewReader(`{"name":"alice"}`)),
	)

	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), `"name":"alice"`) {
		t.Fatalf("unexpected response body %s", response.Body.String())
	}
}

func TestDecodeJSONRejectsBodiesOverLimit(t *testing.T) {
	router := NewRouter()
	router.Post("/decode", func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			Name string `json:"name"`
		}
		if !DecodeJSON(w, r, &request, 4) {
			return
		}
		WriteJSON(w, http.StatusOK, map[string]string{"name": request.Name})
	})

	response := httptest.NewRecorder()
	router.ServeHTTP(
		response,
		httptest.NewRequest(http.MethodPost, "/decode", strings.NewReader(`{"name":"alice"}`)),
	)

	if response.Code != http.StatusOK {
		t.Fatalf("expected transport status 200, got %d: %s", response.Code, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), `"internal_code":20005`) {
		t.Fatalf("unexpected response body %s", response.Body.String())
	}
}

func TestDecodeJSONWithOptionsAllowsUnknownFieldsByDefault(t *testing.T) {
	request := httptest.NewRequest(http.MethodPost, "/decode", strings.NewReader(`{"name":"alice","extra":true}`))
	response := httptest.NewRecorder()
	var body struct {
		Name string `json:"name"`
	}

	err := DecodeJSONWithOptions(response, request, &body, DecodeJSONOptions{MaxBytes: 1024})

	if err != nil {
		t.Fatalf("decode error = %v", err)
	}
	if body.Name != "alice" {
		t.Fatalf("name = %q, want alice", body.Name)
	}
}

func TestDecodeJSONWithOptionsRejectsUnknownFieldsWhenStrict(t *testing.T) {
	request := httptest.NewRequest(http.MethodPost, "/decode", strings.NewReader(`{"name":"alice","extra":true}`))
	response := httptest.NewRecorder()
	var body struct {
		Name string `json:"name"`
	}

	err := DecodeJSONWithOptions(response, request, &body, DecodeJSONOptions{MaxBytes: 1024, DisallowUnknownFields: true})

	if err == nil || !strings.Contains(err.Error(), `unknown field "extra"`) {
		t.Fatalf("decode error = %v, want unknown field error", err)
	}
	if response.Body.Len() != 0 {
		t.Fatalf("response body = %q, want no response writes", response.Body.String())
	}
}

func TestDecodeJSONWithOptionsReturnsMaxBytesErrorWithoutWritingResponse(t *testing.T) {
	request := httptest.NewRequest(http.MethodPost, "/decode", strings.NewReader(`{"name":"alice"}`))
	response := httptest.NewRecorder()
	var body struct {
		Name string `json:"name"`
	}

	err := DecodeJSONWithOptions(response, request, &body, DecodeJSONOptions{MaxBytes: 4})

	var maxBytesError *http.MaxBytesError
	if !errors.As(err, &maxBytesError) {
		t.Fatalf("decode error = %T %v, want *http.MaxBytesError", err, err)
	}
	if response.Body.Len() != 0 {
		t.Fatalf("response body = %q, want no response writes", response.Body.String())
	}
}

func TestDecodeJSONStrictRejectsUnknownFields(t *testing.T) {
	request := httptest.NewRequest(http.MethodPost, "/decode", strings.NewReader(`{"name":"alice","extra":true}`))
	response := httptest.NewRecorder()
	var body struct {
		Name string `json:"name"`
	}

	err := DecodeJSONStrict(response, request, &body, 1024)

	if err == nil || !strings.Contains(err.Error(), `unknown field "extra"`) {
		t.Fatalf("decode error = %v, want unknown field error", err)
	}
}
