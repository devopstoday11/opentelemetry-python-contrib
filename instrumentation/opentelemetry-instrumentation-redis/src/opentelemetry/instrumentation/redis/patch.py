# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# pylint:disable=relative-beyond-top-level
import redis
from wrapt import ObjectProxy, wrap_function_wrapper

from opentelemetry import trace
from opentelemetry.instrumentation.redis import constants

from .util import _extract_conn_attributes, format_command_args
from .version import __version__


def patch():
    """Patch the instrumented methods

    This duplicated doesn't look nice. The nicer alternative is to use an ObjectProxy on top
    of Redis and StrictRedis. However, it means that any "import redis.Redis" won't be instrumented.
    """
    if getattr(redis, "_opentelemetry_patch", False):
        return
    setattr(redis, "_opentelemetry_patch", True)

    if redis.VERSION < (3, 0, 0):
        wrap_function_wrapper(
            "redis", "StrictRedis.execute_command", traced_execute_command
        )
        wrap_function_wrapper("redis", "StrictRedis.pipeline", traced_pipeline)
        wrap_function_wrapper("redis", "Redis.pipeline", traced_pipeline)
        wrap_function_wrapper(
            "redis.client", "BasePipeline.execute", traced_execute_pipeline
        )
        wrap_function_wrapper(
            "redis.client",
            "BasePipeline.immediate_execute_command",
            traced_execute_command,
        )
    else:
        wrap_function_wrapper(
            "redis", "Redis.execute_command", traced_execute_command
        )
        wrap_function_wrapper("redis", "Redis.pipeline", traced_pipeline)
        wrap_function_wrapper(
            "redis.client", "Pipeline.execute", traced_execute_pipeline
        )
        wrap_function_wrapper(
            "redis.client",
            "Pipeline.immediate_execute_command",
            traced_execute_command,
        )


def unwrap(obj, attr):
    func = getattr(obj, attr, None)
    if isinstance(func, ObjectProxy) and hasattr(func, "__wrapped__"):
        setattr(obj, attr, func.__wrapped__)


def unpatch():
    if getattr(redis, "_opentelemetry_patch", False):
        setattr(redis, "_opentelemetry_patch", False)
        if redis.VERSION < (3, 0, 0):
            unwrap(redis.StrictRedis, "execute_command")
            unwrap(redis.StrictRedis, "pipeline")
            unwrap(redis.Redis, "pipeline")
            unwrap(
                redis.client.BasePipeline,  # pylint:disable=no-member
                "execute",
            )
            unwrap(
                redis.client.BasePipeline,  # pylint:disable=no-member
                "immediate_execute_command",
            )
        else:
            unwrap(redis.Redis, "execute_command")
            unwrap(redis.Redis, "pipeline")
            unwrap(redis.client.Pipeline, "execute")
            unwrap(redis.client.Pipeline, "immediate_execute_command")


#
# tracing functions
#
def traced_execute_command(func, instance, args, kwargs):
    tracer = trace.get_tracer(constants.DEFAULT_SERVICE, __version__)

    with tracer.start_as_current_span(constants.CMD) as span:
        span.set_attribute("service", tracer.instrumentation_info.name)
        query = format_command_args(args)
        span.set_attribute(constants.RAWCMD, query)
        for key, value in _get_attributes(instance).items():
            span.set_attribute(key, value)
        span.set_attribute(constants.ARGS_LEN, len(args))
        return func(*args, **kwargs)


# pylint: disable=unused-argument
def traced_pipeline(func, instance, args, kwargs):
    return func(*args, **kwargs)


def traced_execute_pipeline(func, instance, args, kwargs):
    tracer = trace.get_tracer(constants.DEFAULT_SERVICE, __version__)

    cmds = [format_command_args(c) for c, _ in instance.command_stack]
    resource = "\n".join(cmds)

    with tracer.start_as_current_span(constants.CMD) as span:
        span.set_attribute("service", tracer.instrumentation_info.name)
        span.set_attribute(constants.RAWCMD, resource)
        for key, value in _get_attributes(instance).items():
            span.set_attribute(key, value)
        span.set_attribute(constants.PIPELINE_LEN, len(instance.command_stack))
        return func(*args, **kwargs)


def _get_attributes(conn):
    return _extract_conn_attributes(conn.connection_pool.connection_kwargs)