.PHONY: test test-all compile plan

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'

test-all:
	PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
	PYTHONPATH=src python3 -m unittest discover -s comfyui/tests -p 'test_*.py'

compile:
	PYTHONPATH=src python3 -m py_compile $$(find src comfyui tests -name '*.py' -print)

plan:
	adaptive-inference plan --request examples/adaptive/request.json --targets examples/adaptive/targets.json
