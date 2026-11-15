package dev.kaiquebt.anycall.spring;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnyCallSupplier;
import dev.kaiquebt.anycall.core.AnyCallContext;
import dev.kaiquebt.anycall.core.CallOptions;
import dev.kaiquebt.anycall.core.SupplyHandler;
import dev.kaiquebt.anycall.core.SupplyMethod;
import org.aopalliance.intercept.MethodInterceptor;
import org.mockito.ArgumentCaptor;
import org.springframework.aop.framework.ProxyFactory;
import dev.kaiquebt.anycall.spring.apis.SentimentApi;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.autoconfigure.AutoConfigurationPackage;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.TimeUnit;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(OutputCaptureExtension.class)
class AnyCallAutoConfigurationTest {

    private final ApplicationContextRunner runner = new ApplicationContextRunner()
        .withConfiguration(AutoConfigurations.of(AnyCallContractAutoConfiguration.class, AnyCallAutoConfiguration.class));

    @Configuration
    static class FakeClient {
        @Bean
        AnyCallClient anyCallClient() {
            return mock(AnyCallClient.class);
        }
    }

    @Configuration
    static class FakeServer {
        @Bean
        AnyCallServer anyCallServer() {
            return mock(AnyCallServer.class);
        }
    }

    @AnyCallSupplier
    static class Analyzer {
        @Supply(methodName = "analyze-sentiment")
        public Map<String, Object> analyze(AnyCallContext ctx, Map<String, Object> request) {
            return request;
        }
    }

    @Configuration
    static class WithSupplier {
        @Bean
        Analyzer analyzer() {
            return new Analyzer();
        }
    }

    @Configuration
    @AutoConfigurationPackage(basePackageClasses = SentimentApi.class)
    static class AppPackages {
    }

    @Test
    void anycallMustBeOfTheSameContract() {
        AnyCallContractAutoConfiguration.checkContract("0.11.1", "0.11.2");
        AnyCallContractAutoConfiguration.checkContract("0.11.1", "0.11.0");
        assertThatThrownBy(() -> AnyCallContractAutoConfiguration.checkContract("0.11.1", "0.12.0"))
            .hasMessage("anycall-spring 0.11.1 is for contract 0.11, but anycall 0.12.0 is of contract 0.12: use anycall 0.11.x");
    }

    @Test
    void versionsThatArentReleasesArentChecked() {
        AnyCallContractAutoConfiguration.checkContract("0-SNAPSHOT", "0.12.0");
        AnyCallContractAutoConfiguration.checkContract("0.11.1", null);
    }

    @Test
    void theApplicationsOwnClientWins() {
        runner.withUserConfiguration(FakeClient.class).run(context -> {
            assertThat(context).hasSingleBean(AnyCallClient.class);
            assertThat(context.getBean(AnyCallClient.class).getClass().getName()).contains("Mockito");
        });
    }

    @Test
    void noClientWhenDisabled() {
        runner.withPropertyValues("anycall.client.enabled=false")
            .run(context -> assertThat(context).doesNotHaveBean(AnyCallClient.class));
    }

    @Test
    void noServerWithoutSuppliers() {
        runner.withUserConfiguration(FakeClient.class)
            .run(context -> assertThat(context).doesNotHaveBean(AnyCallServerLifecycle.class));
    }

    @Configuration
    static class TwoAnalyzers {
        static final AnyCallServer server = mock(AnyCallServer.class);

        @Bean
        AnyCallServer anyCallServer() {
            return server;
        }

        @Bean
        Analyzer analyzer() {
            return new Analyzer();
        }

        @Bean
        Analyzer otherAnalyzer() {
            return new Analyzer();
        }

        @Bean
        Analyzer thirdAnalyzer() {
            return new Analyzer();
        }

        @Bean
        Logger logger() {
            return new Logger();
        }

        @Bean
        Logger otherLogger() {
            return new Logger();
        }
    }

    @AnyCallSupplier
    static class Logger {
        @Supply(methodName = "log")
        public Map<String, Object> log(AnyCallContext ctx, Map<String, Object> request) {
            return request;
        }
    }

    @Test
    void everyMethodSuppliedByMoreThanOneBeanIsNamedAtOnce() {
        runner.withUserConfiguration(FakeClient.class, TwoAnalyzers.class)
            .run(context -> assertThat(context).getFailure().hasStackTraceContaining(
                "AnyCall methods supplied by more than one bean, where only one may: "
                + "'analyze-sentiment' by analyzer, otherAnalyzer, thirdAnalyzer; 'log' by logger, otherLogger"));
        verify(TwoAnalyzers.server, never()).register(any(SupplyMethod.class), any());
        verify(TwoAnalyzers.server, never()).start();
    }

    @Test
    void suppliersAreRegisteredAndServedOnStart() {
        runner.withUserConfiguration(FakeClient.class, FakeServer.class, WithSupplier.class).run(context -> {
            AnyCallServer server = context.getBean(AnyCallServer.class);
            assertThat(context.getBean(AnyCallServerLifecycle.class).isRunning()).isTrue();
            verify(server).register(eq(new SupplyMethod("analyze-sentiment", 1, Map.class, Map.class)),
                any(SupplyHandler.class));
            verify(server).start();
        });
    }

    /** A bean behind a proxy, with advice that counts the calls going through it. */
    @Configuration
    static class AdvisedSupplier {
        static final AtomicInteger advised = new AtomicInteger();

        @Bean
        Analyzer analyzer() {
            ProxyFactory factory = new ProxyFactory(new Analyzer());
            factory.setProxyTargetClass(true);
            factory.addAdvice((MethodInterceptor) invocation -> {
                advised.incrementAndGet();
                return invocation.proceed();
            });
            return (Analyzer) factory.getProxy();
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    void aSupplyMethodIsCalledThroughTheBeansProxySoItsAdviceRuns() throws Exception {
        runner.withUserConfiguration(FakeClient.class, FakeServer.class, AdvisedSupplier.class).run(context -> {
            ArgumentCaptor<SupplyHandler<Object, Object>> handler = ArgumentCaptor.forClass(SupplyHandler.class);
            verify(context.getBean(AnyCallServer.class)).register(
                eq(new SupplyMethod("analyze-sentiment", 1, Map.class, Map.class)), handler.capture());

            Object response = handler.getValue().handle(new AnyCallContext("r1", "analyze-sentiment"),
                Map.of("text", "bom"));

            assertThat(response).isEqualTo(Map.of("text", "bom"));
            assertThat(AdvisedSupplier.advised).hasValue(1);
        });
    }

    @AnyCallSupplier
    static class PrivateSupplier {
        @Supply(methodName = "hidden")
        private Map<String, Object> hidden(AnyCallContext ctx, Map<String, Object> request) {
            return request;
        }
    }

    @Configuration
    static class ProxiedPrivateSupplier {
        @Bean
        PrivateSupplier privateSupplier() {
            ProxyFactory factory = new ProxyFactory(new PrivateSupplier());
            factory.setProxyTargetClass(true);
            factory.addAdvice((MethodInterceptor) invocation -> invocation.proceed());
            return (PrivateSupplier) factory.getProxy();
        }
    }

    @Test
    void aPrivateSupplyMethodOnAProxiedBeanFailsTheContext() {
        runner.withUserConfiguration(FakeClient.class, FakeServer.class, ProxiedPrivateSupplier.class)
            .run(context -> assertThat(context).getFailure()
                .hasStackTraceContaining("@Supply method hidden can't be called through its proxy; make it public"));
    }

    @Configuration
    static class StuckServer {
        static final CountDownLatch interrupted = new CountDownLatch(1);

        @Bean
        AnyCallServer anyCallServer() throws Exception {
            AnyCallServer server = mock(AnyCallServer.class);
            doAnswer(invocation -> {
                try {
                    new CountDownLatch(1).await();
                } catch (InterruptedException e) {
                    interrupted.countDown();
                }
                return null;
            }).when(server).stop();
            return server;
        }
    }

    @Test
    void aStopThatOutlastsTheShutdownTimeoutIsGivenUp(CapturedOutput output) throws Exception {
        long start = System.nanoTime();
        runner.withUserConfiguration(FakeClient.class, StuckServer.class, WithSupplier.class)
            .withPropertyValues("anycall.server.shutdown-timeout=200ms")
            .run(context -> assertThat(context).hasNotFailed());
        assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(5));
        assertThat(StuckServer.interrupted.await(5, TimeUnit.SECONDS)).isTrue();
        assertThat(output).contains("giving up on them");
    }

    @Test
    void theShutdownTimeoutMustBePositive() {
        runner.withUserConfiguration(FakeClient.class, FakeServer.class, WithSupplier.class)
            .withPropertyValues("anycall.server.shutdown-timeout=0s")
            .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void noServerWhenDisabled(CapturedOutput output) {
        runner.withUserConfiguration(FakeClient.class, WithSupplier.class)
            .withPropertyValues("anycall.server.enabled=false")
            .run(context -> assertThat(context).doesNotHaveBean(AnyCallServer.class));
        assertThat(output).contains("anycall.server.enabled=false: 1 @AnyCallSupplier bean(s) not served: analyzer");
    }

    @Test
    void nothingToSayWhenDisabledWithoutSuppliers(CapturedOutput output) {
        runner.withUserConfiguration(FakeClient.class)
            .withPropertyValues("anycall.server.enabled=false")
            .run(context -> assertThat(context).hasNotFailed());
        assertThat(output).doesNotContain("not served");
    }

    @Configuration
    @EnableAnyCallApis(basePackages = "dev.kaiquebt.anycall.spring.brokenapis")
    static class WithBrokenApi {
    }

    @Test
    void aBrokenInterfaceFailsTheContextEvenIfNothingInjectsIt() {
        runner.withUserConfiguration(FakeClient.class, WithBrokenApi.class)
            .run(context -> assertThat(context).getFailure().rootCause()
                .hasMessageContaining("BrokenApi.two must take at most one argument"));
    }

    @Test
    void anInterfaceWithoutAClientFailsTheContext() {
        runner.withUserConfiguration(AppPackages.class)
            .withPropertyValues("anycall.client.enabled=false")
            .run(context -> assertThat(context).getFailure()
                .hasStackTraceContaining("needs an AnyCallClient bean and there's none"));
    }

    @Test
    void apiInterfacesOfTheApplicationsPackagesBecomeBeans() {
        runner.withUserConfiguration(FakeClient.class, AppPackages.class).run(context -> {
            assertThat(context).hasSingleBean(SentimentApi.class);
            AnyCallClient client = context.getBean(AnyCallClient.class);
            when(client.call(eq("analyze-sentiment"), any(), eq(SentimentApi.Sentiment.class), any(CallOptions.class)))
                .thenReturn(new SentimentApi.Sentiment("positive"));

            assertThat(context.getBean(SentimentApi.class).analyze(Map.of("text", "bom")).label()).isEqualTo("positive");
        });
    }

    @Test
    void configurableCallsReadTheContextsProperties() {
        runner.withUserConfiguration(FakeClient.class, AppPackages.class)
            .withPropertyValues("sentiment.method=renamed", "sentiment.timeout=750ms", "sentiment.max-queue=9")
            .run(context -> {
                AnyCallClient client = context.getBean(AnyCallClient.class);
                context.getBean(SentimentApi.class).analyzeConfigured(Map.of());
                org.mockito.ArgumentCaptor<CallOptions> options = org.mockito.ArgumentCaptor.forClass(CallOptions.class);
                verify(client).call(eq("renamed"), any(), eq(SentimentApi.Sentiment.class), options.capture());
                assertThat(options.getValue().timeoutOr(null)).isEqualTo(Duration.ofMillis(750));
                assertThat(options.getValue().maxQueueDepthOr(null)).isEqualTo(9L);
            });
    }

    @Test
    void aCallWithAMissingPropertyFailsTheContext() {
        runner.withUserConfiguration(FakeClient.class, NeedsAProperty.class)
            .run(context -> assertThat(context).hasFailed()
                .getFailure().rootCause().hasMessageContaining("required.timeout"));
    }

    @dev.kaiquebt.anycall.spring.AnyCallApi
    public interface NeedsAPropertyApi {
        @Call(value = "x", timeout = "${required.timeout}")
        String call(Object request);
    }

    @Configuration
    static class NeedsAProperty {
        @Bean
        AnyCallApiFactoryBean<NeedsAPropertyApi> needsAPropertyApi() {
            return new AnyCallApiFactoryBean<>(NeedsAPropertyApi.class);
        }

        @Bean
        Object injectsIt(NeedsAPropertyApi api) {
            return api;
        }
    }

    @Test
    void enableAnyCallApisLooksInTheGivenPackages() {
        runner.withUserConfiguration(FakeClient.class, ExplicitApis.class)
            .run(context -> assertThat(context).hasSingleBean(SentimentApi.class));
    }

    @Configuration
    @EnableAnyCallApis(basePackageClasses = SentimentApi.class)
    static class ExplicitApis {
    }

    @Test
    void clientDefaultsComeFromProperties() {
        AnyCallProperties.Client client = new AnyCallProperties.Client();
        client.setTimeout(Duration.ofSeconds(30));
        client.setMaxQueueDepth(100L);

        CallOptions defaults = AnyCallAutoConfiguration.callDefaults(client);

        assertThat(defaults.timeoutOr(null)).isEqualTo(Duration.ofSeconds(30));
        assertThat(defaults.maxQueueDepthOr(null)).isEqualTo(100L);
        assertThat(AnyCallAutoConfiguration.callDefaults(new AnyCallProperties.Client()).timeoutOr(Duration.ZERO))
            .isEqualTo(Duration.ZERO);
    }
}
