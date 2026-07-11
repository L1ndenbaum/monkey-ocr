package httpapi

import (
	"fmt"
	"io"
	"os"
)

func seekableBody(body io.ReadCloser) (*os.File, int64, error) {
	defer body.Close()

	file, err := os.CreateTemp("", "storage-service-put-*")
	if err != nil {
		return nil, 0, fmt.Errorf("create temporary upload body: %w", err)
	}

	cleanup := func() {
		name := file.Name()
		_ = file.Close()
		_ = os.Remove(name)
	}

	contentLength, err := io.Copy(file, body)
	if err != nil {
		cleanup()
		return nil, 0, fmt.Errorf("spool upload body: %w", err)
	}

	if _, err := file.Seek(0, io.SeekStart); err != nil {
		cleanup()
		return nil, 0, fmt.Errorf("rewind upload body: %w", err)
	}

	return file, contentLength, nil
}
