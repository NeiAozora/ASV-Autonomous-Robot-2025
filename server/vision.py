import cv2
import numpy as np
import math

class AdaptiveObjectDetector:
    def __init__(self):
        # Default HSV ranges - akan diupdate via trackbar
        self.red_lower = np.array([0, 100, 100])
        self.red_upper = np.array([10, 255, 255])
        self.red_lower2 = np.array([170, 100, 100])
        self.red_upper2 = np.array([180, 255, 255])
        
        self.green_lower = np.array([35, 50, 50])
        self.green_upper = np.array([85, 255, 255])
        
        self.blue_lower = np.array([100, 50, 50])
        self.blue_upper = np.array([130, 255, 255])
        
        # Parameter deteksi
        self.min_radius = 10
        self.max_radius = 100
        self.min_area = 100
        self.circularity_threshold = 0.6
        
        # Tracking untuk adaptive threshold
        self.color_ranges_updated = False
        
    def create_trackbars(self):
        """Membuat trackbar untuk kalibrasi warna real-time"""
        cv2.namedWindow('Color Calibration')
        
        # Trackbar untuk Red
        cv2.createTrackbar('Red H Low', 'Color Calibration', 0, 180, self.nothing)
        cv2.createTrackbar('Red H High', 'Color Calibration', 10, 180, self.nothing)
        cv2.createTrackbar('Red S Low', 'Color Calibration', 100, 255, self.nothing)
        cv2.createTrackbar('Red S High', 'Color Calibration', 255, 255, self.nothing)
        cv2.createTrackbar('Red V Low', 'Color Calibration', 100, 255, self.nothing)
        cv2.createTrackbar('Red V High', 'Color Calibration', 255, 255, self.nothing)
        
        # Trackbar untuk Green
        cv2.createTrackbar('Green H Low', 'Color Calibration', 35, 180, self.nothing)
        cv2.createTrackbar('Green H High', 'Color Calibration', 85, 180, self.nothing)
        cv2.createTrackbar('Green S Low', 'Color Calibration', 50, 255, self.nothing)
        cv2.createTrackbar('Green S High', 'Color Calibration', 255, 255, self.nothing)
        cv2.createTrackbar('Green V Low', 'Color Calibration', 50, 255, self.nothing)
        cv2.createTrackbar('Green V High', 'Color Calibration', 255, 255, self.nothing)
        
        # Trackbar untuk Blue
        cv2.createTrackbar('Blue H Low', 'Color Calibration', 100, 180, self.nothing)
        cv2.createTrackbar('Blue H High', 'Color Calibration', 130, 180, self.nothing)
        cv2.createTrackbar('Blue S Low', 'Color Calibration', 50, 255, self.nothing)
        cv2.createTrackbar('Blue S High', 'Color Calibration', 255, 255, self.nothing)
        cv2.createTrackbar('Blue V Low', 'Color Calibration', 50, 255, self.nothing)
        cv2.createTrackbar('Blue V High', 'Color Calibration', 255, 255, self.nothing)
        
        # Trackbar untuk parameter deteksi
        cv2.createTrackbar('Min Area', 'Color Calibration', 100, 1000, self.nothing)
        cv2.createTrackbar('Circularity', 'Color Calibration', 60, 100, self.nothing)
        
    def nothing(self, x):
        pass
    
    def update_color_ranges(self):
        """Update HSV ranges dari trackbar"""
        # Red ranges
        self.red_lower = np.array([
            cv2.getTrackbarPos('Red H Low', 'Color Calibration'),
            cv2.getTrackbarPos('Red S Low', 'Color Calibration'),
            cv2.getTrackbarPos('Red V Low', 'Color Calibration')
        ])
        self.red_upper = np.array([
            cv2.getTrackbarPos('Red H High', 'Color Calibration'),
            cv2.getTrackbarPos('Red S High', 'Color Calibration'),
            cv2.getTrackbarPos('Red V High', 'Color Calibration')
        ])
        self.red_lower2 = np.array([170, self.red_lower[1], self.red_lower[2]])
        self.red_upper2 = np.array([180, self.red_upper[1], self.red_upper[2]])
        
        # Green range
        self.green_lower = np.array([
            cv2.getTrackbarPos('Green H Low', 'Color Calibration'),
            cv2.getTrackbarPos('Green S Low', 'Color Calibration'),
            cv2.getTrackbarPos('Green V Low', 'Color Calibration')
        ])
        self.green_upper = np.array([
            cv2.getTrackbarPos('Green H High', 'Color Calibration'),
            cv2.getTrackbarPos('Green S High', 'Color Calibration'),
            cv2.getTrackbarPos('Green V High', 'Color Calibration')
        ])
        
        # Blue range
        self.blue_lower = np.array([
            cv2.getTrackbarPos('Blue H Low', 'Color Calibration'),
            cv2.getTrackbarPos('Blue S Low', 'Color Calibration'),
            cv2.getTrackbarPos('Blue V Low', 'Color Calibration')
        ])
        self.blue_upper = np.array([
            cv2.getTrackbarPos('Blue H High', 'Color Calibration'),
            cv2.getTrackbarPos('Blue S High', 'Color Calibration'),
            cv2.getTrackbarPos('Blue V High', 'Color Calibration')
        ])
        
        # Update parameter deteksi
        self.min_area = cv2.getTrackbarPos('Min Area', 'Color Calibration')
        self.circularity_threshold = cv2.getTrackbarPos('Circularity', 'Color Calibration') / 100.0
    
    def detect_objects(self, frame):
        """Deteksi semua objek (bola dan kotak)"""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # Update color ranges dari trackbar
        self.update_color_ranges()
        
        # Mask untuk berbagai warna
        red_mask1 = cv2.inRange(hsv, self.red_lower, self.red_upper)
        red_mask2 = cv2.inRange(hsv, self.red_lower2, self.red_upper2)
        red_mask = cv2.bitwise_or(red_mask1, red_mask2)
        
        green_mask = cv2.inRange(hsv, self.green_lower, self.green_upper)
        blue_mask = cv2.inRange(hsv, self.blue_lower, self.blue_upper)
        
        # Operasi morfologi
        kernel = np.ones((5,5), np.uint8)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
        green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, kernel)
        blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_CLOSE, kernel)
        
        # Deteksi objek
        results = {
            'red_balls': self._find_circles(red_mask, 'red'),
            'green_balls': self._find_circles(green_mask, 'green'),
            'green_boxes': self._find_rectangles(green_mask, 'green'),
            'blue_boxes': self._find_rectangles(blue_mask, 'blue')
        }
        
        return results, [red_mask, green_mask, blue_mask]
    
    def _find_circles(self, mask, color):
        """Temukan objek berbentuk lingkaran (bola)"""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        circles = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue
            
            # Deteksi lingkaran
            ((x, y), radius) = cv2.minEnclosingCircle(contour)
            center = (int(x), int(y))
            radius = int(radius)
            
            if radius < self.min_radius or radius > self.max_radius:
                continue
            
            # Circularity check
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
                
            circularity = 4 * math.pi * area / (perimeter * perimeter)
            if circularity < self.circularity_threshold:
                continue
            
            circles.append({
                'center': center,
                'radius': radius,
                'area': area,
                'circularity': circularity
            })
            
        return circles
    
    def _find_rectangles(self, mask, color):
        """Temukan objek berbentuk kotak"""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        rectangles = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area * 2:  # Kotak biasanya lebih besar
                continue
            
            # Approximate contour
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            
            # Jika memiliki 4 sudut, anggap sebagai kotak
            if len(approx) == 4:
                x, y, w, h = cv2.boundingRect(contour)
                center = (int(x + w/2), int(y + h/2))
                
                rectangles.append({
                    'center': center,
                    'width': w,
                    'height': h,
                    'area': area,
                    'bbox': (x, y, w, h)
                })
            
        return rectangles
    
    def calculate_offsets_and_distances(self, objects, frame_width, frame_height):
        """Hitung offset dan jarak untuk semua objek"""
        results = {}
        frame_center_x = frame_width // 2
        frame_center_y = frame_height // 2
        
        # Untuk setiap jenis objek, hitung jarak dan offset
        obj_types = ['red_balls', 'green_balls', 'green_boxes', 'blue_boxes']
        
        for obj_type in obj_types:
            if objects[obj_type]:
                obj = objects[obj_type][0]  # Ambil objek pertama
                center = obj['center']
                
                # Hitung offset dari tengah frame
                offset_x = center[0] - frame_center_x
                offset_y = center[1] - frame_center_y
                normalized_offset_x = offset_x / frame_center_x
                normalized_offset_y = offset_y / frame_center_y
                
                # Estimasi jarak (berdasarkan area/radius)
                if 'radius' in obj:  # Bola
                    distance = (1000 / obj['radius']) * 10
                else:  # Kotak
                    distance = (50000 / obj['area']) * 5
                
                results[f'{obj_type}_distance'] = distance
                results[f'{obj_type}_offset_x'] = offset_x
                results[f'{obj_type}_offset_y'] = offset_y
                results[f'{obj_type}_normalized_x'] = normalized_offset_x
                results[f'{obj_type}_normalized_y'] = normalized_offset_y
                results[f'{obj_type}_center'] = center
        
        # Hitung offset antara dua bola jika keduanya terdeteksi
        if objects['red_balls'] and objects['green_balls']:
            red_center = objects['red_balls'][0]['center']
            green_center = objects['green_balls'][0]['center']
            
            # Titik tengah antara dua bola
            mid_point = (
                (red_center[0] + green_center[0]) // 2,
                (red_center[1] + green_center[1]) // 2
            )
            
            # Offset dari tengah frame
            balls_offset_x = mid_point[0] - frame_center_x
            balls_normalized_offset = balls_offset_x / frame_center_x
            
            results['balls_mid_point'] = mid_point
            results['balls_offset_x'] = balls_offset_x
            results['balls_normalized_offset'] = balls_normalized_offset
        
        return results
    
    def draw_detections(self, frame, objects, measurements):
        """Gambar hasil deteksi pada frame"""
        # Warna untuk berbagai objek
        colors = {
            'red_balls': (0, 0, 255),
            'green_balls': (0, 255, 0),
            'green_boxes': (0, 255, 0),
            'blue_boxes': (255, 0, 0)
        }
        
        # Gambar deteksi untuk setiap jenis objek
        for obj_type in ['red_balls', 'green_balls', 'green_boxes', 'blue_boxes']:
            for obj in objects[obj_type]:
                center = obj['center']
                color = colors[obj_type]
                
                if 'radius' in obj:  # Bola
                    radius = obj['radius']
                    cv2.circle(frame, center, radius, color, 2)
                    cv2.circle(frame, center, 2, color, 3)
                    
                    label = f"{obj_type} R:{radius}"
                    cv2.putText(frame, label, 
                               (center[0] - 30, center[1] - radius - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                else:  # Kotak
                    x, y, w, h = obj['bbox']
                    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                    cv2.circle(frame, center, 3, color, -1)
                    
                    label = f"{obj_type} A:{obj['area']}"
                    cv2.putText(frame, label, 
                               (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        # Gambar informasi tambahan
        self._draw_measurements(frame, measurements, frame.shape[1], frame.shape[0])
        
        return frame
    
    def _draw_measurements(self, frame, measurements, frame_width, frame_height):
        """Gambar informasi pengukuran pada frame"""
        frame_center_x = frame_width // 2
        frame_center_y = frame_height // 2
        
        # Garis tengah frame
        cv2.line(frame, (frame_center_x, 0), (frame_center_x, frame_height), 
                (0, 255, 255), 1)
        cv2.line(frame, (0, frame_center_y), (frame_width, frame_center_y), 
                (0, 255, 255), 1)
        
        # Titik tengah frame
        cv2.circle(frame, (frame_center_x, frame_center_y), 5, (0, 255, 255), -1)
        
        # Info offset dan jarak
        y_offset = 30
        obj_types = ['red_balls', 'green_balls', 'green_boxes', 'blue_boxes']
        
        for obj_type in obj_types:
            key = f'{obj_type}_normalized_x'
            if key in measurements:
                offset_x = measurements[f'{obj_type}_normalized_x']
                distance = measurements[f'{obj_type}_distance']
                
                info_text = f"{obj_type}: Offset={offset_x:.2f}, Dist={distance:.1f}"
                cv2.putText(frame, info_text, (10, y_offset), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                y_offset += 20
        
        # Info offset antara dua bola
        if 'balls_normalized_offset' in measurements:
            offset_info = f"Balls Mid Offset: {measurements['balls_normalized_offset']:.3f}"
            cv2.putText(frame, offset_info, (frame_width - 300, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            
            # Gambar titik tengah antara dua bola
            mid_point = measurements['balls_mid_point']
            cv2.circle(frame, mid_point, 5, (255, 255, 0), -1)
            
            # Garis dari tengah frame ke titik tengah bola
            cv2.line(frame, (frame_center_x, frame_center_y), mid_point, 
                    (255, 255, 0), 2)

def main():
    detector = AdaptiveObjectDetector()
    detector.create_trackbars()
    
    # Gunakan webcam
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    if not cap.isOpened():
        print("Error: Cannot open camera")
        return
    
    print("Adaptive Object Detection started!")
    print("Instructions:")
    print("- Use trackbars to calibrate color ranges")
    print("- Press 'q' to quit")
    print("- Press 's' to save current settings")
    print("- Press 'r' to reset to default")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Cannot read frame")
            break
        
        frame_height, frame_width = frame.shape[:2]
        
        # Deteksi objek
        objects, masks = detector.detect_objects(frame)
        
        # Hitung pengukuran
        measurements = detector.calculate_offsets_and_distances(objects, frame_width, frame_height)
        
        # Gambar hasil
        result_frame = detector.draw_detections(frame.copy(), objects, measurements)
        
        # Tampilkan frame hasil
        cv2.imshow('Object Detection', result_frame)
        
        # PERBAIKAN: Tampilkan masks dengan ukuran yang sesuai
        mask_display = np.zeros((240, 640, 3), dtype=np.uint8)
        if len(masks) >= 3:
            # Resize masks agar sesuai dengan area yang dialokasikan
            h, w = 160, 213
            
            # Red mask
            red_mask_resized = cv2.resize(masks[0], (w, h))
            red_mask_bgr = cv2.cvtColor(red_mask_resized, cv2.COLOR_GRAY2BGR)
            mask_display[0:h, 0:w] = red_mask_bgr
            
            # Green mask
            green_mask_resized = cv2.resize(masks[1], (w, h))
            green_mask_bgr = cv2.cvtColor(green_mask_resized, cv2.COLOR_GRAY2BGR)
            mask_display[0:h, w:2*w] = green_mask_bgr
            
            # Blue mask
            blue_mask_resized = cv2.resize(masks[2], (640 - 2*w, h))
            blue_mask_bgr = cv2.cvtColor(blue_mask_resized, cv2.COLOR_GRAY2BGR)
            mask_display[0:h, 2*w:640] = blue_mask_bgr
            
            # Labels untuk masks
            cv2.putText(mask_display, "Red Mask", (50, 20), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(mask_display, "Green Mask", (263, 20), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(mask_display, "Blue Mask", (476, 20), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        
        cv2.imshow('Color Masks', mask_display)
        
        # Print status ke console
        print("\r" + " " * 100, end="")  # Clear line
        status_parts = []
        for obj_type in ['red_balls', 'green_balls', 'green_boxes', 'blue_boxes']:
            if objects[obj_type]:
                status_parts.append(f"{obj_type}: ✓")
            else:
                status_parts.append(f"{obj_type}: ✗")
        
        if 'balls_normalized_offset' in measurements:
            status_parts.append(f"Offset: {measurements['balls_normalized_offset']:.3f}")
        
        print(f"\r{' | '.join(status_parts)}", end="")
        
        # Keyboard controls
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            # Save current settings
            print("\nSettings saved!")
        elif key == ord('r'):
            # Reset trackbars to default
            pass  # Bisa implementasi reset jika needed
    
    cap.release()
    cv2.destroyAllWindows()
    print("\nProgram terminated")

if __name__ == "__main__":
    main()