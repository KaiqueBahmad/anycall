package dev.kaiquebt.anycall.payload;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JavaType;
import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallContext;
import dev.kaiquebt.anycall.core.AnyCallSupplier;
import dev.kaiquebt.anycall.server.SupplyScanner;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.lang.reflect.Type;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.*;

class PayloadsTest {

    public enum Color { RED }

    public record Point(double x, double y) {
    }

    public record Category(String name, List<Category> children) {
    }

    public record Product(String name, Map<String, Integer> stock, List<String> tags, String note) {
    }

    public record Event(String name, Instant at) {
    }

    public record Counter(String name, int count) {
    }

    public record Id(long id) {
    }

    public static class Pojo {
        public String name;
        public Integer size;
    }

    private static Type type(TypeReference<?> reference) {
        return reference.getType();
    }

    private static JavaType javaType(TypeReference<?> reference) {
        return Payloads.javaType(reference.getType());
    }

    // Declaring

    static Stream<Type> payloadTypes() {
        return Stream.of(boolean.class, Boolean.class, int.class, Integer.class, long.class, Long.class,
            float.class, double.class, Double.class, String.class, Point[].class, double[].class,
            Point.class, Category.class, Product.class, Pojo.class,
            type(new TypeReference<List<Point>>() { }),
            type(new TypeReference<Map<String, List<Double>>>() { }),
            type(new TypeReference<ArrayList<String>>() { }));
    }

    @ParameterizedTest
    @MethodSource("payloadTypes")
    void payloadTypesAreAccepted(Type type) {
        Payloads.checkType(type, "it");
    }

    static Stream<Type> otherTypes() {
        return Stream.of(
            byte[].class,
            Color.class,
            Instant.class,
            UUID.class,
            BigDecimal.class,
            short.class,
            char.class,
            Object.class,
            List.class,
            Map.class,
            type(new TypeReference<Optional<String>>() { }),
            type(new TypeReference<Set<String>>() { }),
            type(new TypeReference<Map<Integer, String>>() { }),
            type(new TypeReference<Map<String, Object>>() { }));
    }

    @ParameterizedTest
    @MethodSource("otherTypes")
    void otherTypesAreRejected(Type type) {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class, () -> Payloads.checkType(type, "it"));
        assertTrue(e.getMessage().contains("AnyCall payload type"), e.getMessage());
    }

    @Test
    void aRejectedFieldIsNamed() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> Payloads.checkType(type(new TypeReference<List<Event>>() { }), "method log's request"));
        assertEquals("method log's request: Event.at is Instant, not an AnyCall payload type", e.getMessage());
    }

    @Test
    void aContainerOfARejectedTypeNamesTheContainer() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> Payloads.checkType(type(new TypeReference<Map<String, Object>>() { }), "method echo's request"));
        assertEquals("method echo's request is Map<String, Object>, and Object isn't an AnyCall payload type",
            e.getMessage());
    }

    // Writing

    @Test
    void valuesAreWrittenAsJson() {
        Map<String, Integer> stock = new HashMap<>();
        stock.put("sp", 12);
        assertEquals("{\"name\":\"fone\",\"stock\":{\"sp\":12},\"tags\":[\"audio\"],\"note\":null}",
            Payloads.toJson(new Product("fone", stock, List.of("audio"), null)));
        assertEquals("[1.5,2.0]", Payloads.toJson(new double[] {1.5, 2.0}));
    }

    @Test
    void integersUpToTheLimitAreWritten() {
        assertEquals(String.valueOf(Payloads.MAX_INTEGER), Payloads.toJson(Payloads.MAX_INTEGER));
        assertEquals(String.valueOf(-Payloads.MAX_INTEGER), Payloads.toJson(-Payloads.MAX_INTEGER));
    }

    static Stream<Arguments> valuesOutsideTheRules() {
        return Stream.of(
            Arguments.of(Payloads.MAX_INTEGER + 1, "2^53"),
            Arguments.of(new Id(-(Payloads.MAX_INTEGER + 1)), "Id.id"),
            Arguments.of(Double.NaN, "NaN"),
            Arguments.of(List.of(Float.POSITIVE_INFINITY), "NaN or infinity"),
            Arguments.of(Color.RED, "Color, not an AnyCall payload type"),
            Arguments.of(new byte[] {1}, "byte[], not an AnyCall payload type"),
            Arguments.of(Map.of(1, "a"), "map keys are Strings"),
            Arguments.of(Set.of("a"), "not an AnyCall payload type"),
            Arguments.of(Optional.of("a"), "Optional, not an AnyCall payload type"),
            Arguments.of(new Event("x", Instant.EPOCH), "Event.at"));
    }

    @ParameterizedTest
    @MethodSource("valuesOutsideTheRules")
    void valuesOutsideTheRulesAreNotWritten(Object value, String error) {
        PayloadException e = assertThrows(PayloadException.class, () -> Payloads.toJson(value));
        assertTrue(e.getMessage().contains(error), e.getMessage());
    }

    @Test
    void cyclicDataIsNotWritten() {
        List<Object> list = new ArrayList<>();
        list.add(list);
        PayloadException e = assertThrows(PayloadException.class, () -> Payloads.toJson(list));
        assertTrue(e.getMessage().contains("tree"), e.getMessage());
    }

    @Test
    void theSameObjectTwiceIsWrittenTwice() {
        Point point = new Point(1, 2);
        assertEquals("[{\"x\":1.0,\"y\":2.0},{\"x\":1.0,\"y\":2.0}]", Payloads.toJson(List.of(point, point)));
    }

    // Reading

    @Test
    void jsonIsReadIntoTheDeclaredType() {
        Object product = Payloads.fromJson("{\"name\":\"fone\",\"stock\":{\"sp\":12,\"ba\":1},\"tags\":[],\"note\":\"x\"}",
            Payloads.javaType(Product.class));
        assertEquals(new Product("fone", Map.of("sp", 12, "ba", 1), List.of(), "x"), product);
    }

    @Test
    void genericsAreReadWithTheirArguments() {
        Object points = Payloads.fromJson("[{\"x\":1,\"y\":2}]", javaType(new TypeReference<List<Point>>() { }));
        assertEquals(List.of(new Point(1, 2)), points);
    }

    @Test
    void aTypeThatRefersToItselfIsRead() {
        Object category = Payloads.fromJson("{\"name\":\"a\",\"children\":[{\"name\":\"b\",\"children\":[]}]}",
            Payloads.javaType(Category.class));
        assertEquals(new Category("a", List.of(new Category("b", List.of()))), category);
    }

    @Test
    void aWholeNullPayloadIsNullForAnyReferenceType() {
        assertNull(Payloads.fromJson("null", Payloads.javaType(Point.class)));
    }

    static Stream<Arguments> jsonThatDoesntFit() {
        return Stream.of(
            Arguments.of("{\"x\":1,\"y\":2,\"z\":3}", Point.class, "no field z"),
            Arguments.of("{\"x\":1}", Point.class, "missing y"),
            Arguments.of("{\"name\":\"a\"}", Pojo.class, "missing size"),
            Arguments.of("{\"x\":null,\"y\":2}", Point.class, "Point.x should be double, got null"),
            Arguments.of("{\"name\":\"a\",\"count\":1.5}", Counter.class, "Counter.count should be int, got a number"),
            Arguments.of("{\"name\":\"a\",\"count\":3000000000}", Counter.class, "past what an int holds"),
            Arguments.of("{\"id\":9007199254740992}", Id.class, "2^53"),
            Arguments.of("true", Integer.class, "got a boolean"),
            Arguments.of("1", Boolean.class, "got a number"),
            Arguments.of("1", String.class, "got a number"),
            Arguments.of("\"1\"", Integer.class, "got a string"),
            Arguments.of("[]", Point.class, "got an array"),
            Arguments.of("null", int.class, "got null"));
    }

    @ParameterizedTest
    @MethodSource("jsonThatDoesntFit")
    void jsonThatDoesntFitIsRejected(String json, Class<?> type, String error) {
        PayloadException e = assertThrows(PayloadException.class, () -> Payloads.fromJson(json, Payloads.javaType(type)));
        assertTrue(e.getMessage().contains(error), e.getMessage());
    }

    @Test
    void anIntegerIsReadAsADouble() {
        assertEquals(new Point(1, 2.5), Payloads.fromJson("{\"x\":1,\"y\":2.5}", Payloads.javaType(Point.class)));
    }

    // Where a server checks

    @AnyCallSupplier
    static class Logger {
        @Supply(methodName = "log")
        public void log(AnyCallContext ctx, Event event) {
        }
    }

    @AnyCallSupplier
    static class Embedder {
        @Supply(methodName = "embed")
        public byte[] embed(AnyCallContext ctx, String text) {
            return new byte[0];
        }
    }

    @AnyCallSupplier
    static class Batch {
        @Supply(methodName = "batch")
        public List<Point> batch(AnyCallContext ctx, List<Point> points) {
            return points;
        }
    }

    @Test
    void scanningRejectsAMethodWhoseTypesArentPayloadTypes() {
        IllegalArgumentException request = assertThrows(IllegalArgumentException.class,
            () -> SupplyScanner.scan(new Logger()));
        assertTrue(request.getMessage().startsWith("method log's request: Event.at is Instant"), request.getMessage());
        IllegalArgumentException response = assertThrows(IllegalArgumentException.class,
            () -> SupplyScanner.scan(new Embedder()));
        assertTrue(response.getMessage().startsWith("method embed's response is byte[]"), response.getMessage());
    }

    @Test
    void scanningKeepsGenericArguments() {
        assertEquals("java.util.List<dev.kaiquebt.anycall.payload.PayloadsTest$Point>",
            SupplyScanner.scan(new Batch()).get(0).parameterType().getTypeName());
    }
}
