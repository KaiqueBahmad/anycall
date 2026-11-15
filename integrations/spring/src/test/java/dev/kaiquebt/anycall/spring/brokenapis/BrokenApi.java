package dev.kaiquebt.anycall.spring.brokenapis;

import dev.kaiquebt.anycall.spring.AnyCallApi;
import dev.kaiquebt.anycall.spring.Call;

/** Nothing injects it; it must still fail the context. */
@AnyCallApi
public interface BrokenApi {

    @Call("x")
    String two(Object a, Object b);
}
