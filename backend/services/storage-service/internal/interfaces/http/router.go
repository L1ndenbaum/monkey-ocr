package httpapi

import sharedhttp "monkeyocr-services-lib-go/http/api"

func NewRouter(handler *Handler) *sharedhttp.Router {
	router := sharedhttp.NewRouter()
	auth := sharedhttp.TokenAuth(sharedhttp.TokenAuthConfig{
		Header:  storageServiceTokenHeader,
		Token:   handler.serviceToken,
		Message: "unauthorized",
	})

	router.Get("/health", handler.HandleHealth)
	router.With(auth).Post("/buckets/ensure", handler.HandleEnsureBucket)
	router.With(auth).Post("/multipart/create", handler.HandleCreateMultipart)
	router.With(auth).Post("/multipart/complete", handler.HandleCompleteMultipart)
	router.With(auth).Post("/multipart/abort", handler.HandleAbortMultipart)
	router.With(auth).Post("/presign/get", handler.HandlePresignGet)
	router.With(auth).Post("/presign/put", handler.HandlePresignPut)
	router.With(auth).Post("/objects/stat", handler.HandleStatObject)
	router.With(auth).Post("/objects/delete", handler.HandleDeleteObject)
	router.With(auth).Get("/objects/*", handler.HandleGetObject)
	router.With(auth).Put("/objects/*", handler.HandlePutObject)
	return router
}
