module dev.kaiquebt.anycall {
    // External dependencies
    requires transitive com.fasterxml.jackson.databind;
    requires org.slf4j;

    // Automatic modules (from unnamed module)
    requires lettuce.core;
    requires io.netty.common;
    requires io.netty.transport;
    requires io.netty.codec;

    // Public API
    exports dev.kaiquebt.anycall.core;
    exports dev.kaiquebt.anycall.annotation;
    exports dev.kaiquebt.anycall.exception;
    exports dev.kaiquebt.anycall.publisher;
    exports dev.kaiquebt.anycall.config;

    // Open for reflection (Jackson, method invocation via reflection)
    opens dev.kaiquebt.anycall.model to com.fasterxml.jackson.databind;
    opens dev.kaiquebt.anycall.server to com.fasterxml.jackson.databind;
}
