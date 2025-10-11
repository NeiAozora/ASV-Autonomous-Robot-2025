from helpers.parallel_runner import ParallelRunner


p = ParallelRunner()

p.add_process("camera_server", "")
p.add_process("camera_server", "")
p.add_process("server_tranceiver", "go run server/tranceiver/main.go", True, None)
