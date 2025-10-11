from helpers.parallel_runner import ParallelRunner


p = ParallelRunner()

p.add_process("camera_server", "bash server/camera/camera_v2_go/run_server.sh")
p.add_process("controller_server", "cd server/control && uvicorn server:app --host 0.0.0.0 --port 2000 --workers 4")
p.add_process("server_tranceiver", "go run server/tranceiver/main.go", True, None)

p.run()