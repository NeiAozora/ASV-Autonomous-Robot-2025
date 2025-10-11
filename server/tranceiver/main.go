package main

import (
	"io"
	"net/http"
	"strconv"
	"time"
)

func main() {
	// Ports tujuan untuk forwarding
	targetPorts := []int{1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000}
	client := &http.Client{Timeout: 5 * time.Second}

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// Mencoba request ke setiap port secara berurutan
		for _, port := range targetPorts {
			targetURL := "http://localhost:" + strconv.Itoa(port) + r.URL.Path
			if r.URL.RawQuery != "" {
				targetURL += "?" + r.URL.RawQuery
			}

			// Membuat request baru
			proxyReq, err := http.NewRequest(r.Method, targetURL, r.Body)
			if err != nil {
				continue // Coba port berikutnya jika gagal
			}

			// Menyalin header dari request asli
			proxyReq.Header = make(http.Header)
			for k, v := range r.Header {
				proxyReq.Header[k] = v
			}

			// Mengirim request
			resp, err := client.Do(proxyReq)
			if err != nil {
				continue // Coba port berikutnya jika gagal
			}
			defer resp.Body.Close()

			// Jika response bukan 404, kembalikan response tersebut
			if resp.StatusCode != http.StatusNotFound {
				// Menyalin header dari response
				for k, v := range resp.Header {
					w.Header()[k] = v
				}
				w.WriteHeader(resp.StatusCode)
				io.Copy(w, resp.Body)
				return
			}
		}

		// Jika semua port mengembalikan 404
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte("404 - All endpoints returned not found"))
	})

	// Menjalankan server pada port 9000
	http.ListenAndServe(":9000", nil)
}