from engine.generate import GENERATORS
from engine.pfm import REGISTRY
from profiling.workload import get_workload, iter_workloads, reset_registry_for_tests
from profiling.workloads import register_all


def test_full_registry_contains_every_pfm_and_generator():
    reset_registry_for_tests()
    register_all()
    ids = {item.id for item in iter_workloads()}
    assert {f"pfm.{name}" for name in REGISTRY} <= ids
    assert {f"generator.{name}" for name in GENERATORS} <= ids


def test_dense_circle_fixture_has_stable_size_and_output():
    reset_registry_for_tests()
    register_all()
    workload = get_workload("pipeline.svg_dense_circles")
    case = workload.prepare()
    output = workload.run(case)
    workload.validate(output)
    assert output.metrics["paths"] == 8000
    assert output.metrics["svg_bytes"] > 400_000


def test_every_quick_workload_has_a_valid_cpu_result():
    reset_registry_for_tests()
    register_all()
    for workload in (item for item in iter_workloads() if item.quick and "cpu" in item.backends):
        output = workload.run(workload.prepare())
        workload.validate(output)
