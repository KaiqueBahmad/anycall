package dev.kaiquebt.anycall.payload;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.BeanDescription;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JavaType;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.introspect.AnnotatedMember;
import com.fasterxml.jackson.databind.introspect.BeanPropertyDefinition;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.lang.reflect.Array;
import java.lang.reflect.Modifier;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The payload types (see LIBRARY.md): what a request or response may be, as JSON itself has it.
 * Internal.
 *
 * <pre>
 * T = boolean | integer | number | string
 *   | array of T | map of string to T | record of fields, each a T
 *   | T or null
 * </pre>
 *
 * In Java: {@code boolean}, {@code int}, {@code long}, {@code float}, {@code double} and their
 * boxes, {@code String}, {@code List<T>} and {@code T[]}, {@code Map<String, T>}, and records and
 * POJOs whose properties are payload types. Every reference type may be null. Three checks, one
 * per moment:
 * <ul>
 *   <li>{@link #checkType}: a declared type, when it's declared. Throws
 *       {@link IllegalArgumentException}.</li>
 *   <li>{@link #toJson}: a value, as it's written. Throws {@link PayloadException}.</li>
 *   <li>{@link #fromJson}: JSON text, read into a declared type. Throws
 *       {@link PayloadException}.</li>
 * </ul>
 */
public final class Payloads {

    /**
     * The integers every language reads exactly: a JSON number is a 64-bit float in some of
     * them, and past this one a float can't tell neighbors apart.
     */
    public static final long MAX_INTEGER = (1L << 53) - 1;

    private static final ObjectMapper MAPPER = JsonMapper.builder()
        .enable(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES)
        .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
        .build();

    private static final JsonNodeFactory NODES = JsonNodeFactory.instance;

    private static final Set<Class<?>> SCALARS = Set.of(
        boolean.class, Boolean.class, int.class, Integer.class, long.class, Long.class,
        float.class, Float.class, double.class, Double.class, String.class);

    private static final Set<JavaType> CHECKED = ConcurrentHashMap.newKeySet();

    /** A record's properties as it's read: name to type. Jackson doesn't cache introspection. */
    private static final Map<JavaType, Map<String, JavaType>> READ_PROPERTIES = new ConcurrentHashMap<>();

    /** A record's properties as it's written: name to accessor. */
    private static final Map<Class<?>, Map<String, AnnotatedMember>> WRITE_PROPERTIES = new ConcurrentHashMap<>();

    private Payloads() {
    }

    /** {@code type} as Jackson resolves it, generic arguments included. */
    public static JavaType javaType(Type type) {
        return MAPPER.constructType(type);
    }

    /** Whether {@code type} declares no payload: {@code void} or {@code Void}. */
    public static boolean isVoid(Type type) {
        return type == void.class || type == Void.class;
    }

    // Declaring

    /**
     * Checks that {@code type} is a payload type. {@code where} names it in the error, such as
     * "method embed's request".
     *
     * @throws IllegalArgumentException naming the field whose type isn't one
     */
    public static void checkType(Type type, String where) {
        if (type == null) {
            throw new IllegalArgumentException(where + " has no type");
        }
        JavaType javaType = javaType(type);
        if (CHECKED.contains(javaType)) {
            return;
        }
        check(javaType, where, javaType, new HashSet<>(), where);
        CHECKED.add(javaType);
    }

    /**
     * Checks {@code type}, found at {@code path} inside {@code declared}: the type as written there,
     * which differs from it inside a list, an array or a map. A field's path starts with
     * {@code where}, what was declared, so its error says which method or call it came from.
     */
    private static void check(JavaType type, String path, JavaType declared, Set<Class<?>> seen, String where) {
        Class<?> raw = type.getRawClass();
        if (SCALARS.contains(raw)) {
            return;
        }
        if ((type.isArrayType() && raw != byte[].class)
                || (type.isCollectionLikeType() && List.class.isAssignableFrom(raw))
                || (type.isMapLikeType() && Map.class.isAssignableFrom(raw)
                    && type.getKeyType().getRawClass() == String.class)) {
            check(type.getContentType(), path, declared, seen, where);
            return;
        }
        if (isRecord(raw)) {
            if (!seen.add(raw)) {
                return; // a type that refers to itself
            }
            readProperties(type).forEach((property, propertyType) ->
                check(propertyType, where + ": " + raw.getSimpleName() + "." + property, propertyType, seen, where));
            return;
        }
        throw new IllegalArgumentException(type.equals(declared)
            ? path + " is " + name(type) + ", not an AnyCall payload type"
            : path + " is " + name(declared) + ", and " + name(type) + " isn't an AnyCall payload type");
    }

    /** {@code type} as it's written in code: {@code Map<String, Object>}, {@code Point[]}. */
    private static String name(JavaType type) {
        if (type.isArrayType()) {
            return name(type.getContentType()) + "[]";
        }
        String raw = type.getRawClass().getSimpleName();
        if (type.containedTypeCount() == 0) {
            return raw;
        }
        List<String> arguments = new ArrayList<>();
        for (int i = 0; i < type.containedTypeCount(); i++) {
            arguments.add(name(type.containedType(i)));
        }
        return raw + "<" + String.join(", ", arguments) + ">";
    }

    /**
     * Whether {@code raw} is a record or POJO the library reads and writes by its properties:
     * a concrete class of the caller's own, not one of the JDK's or Jackson's.
     */
    private static boolean isRecord(Class<?> raw) {
        if (raw.isPrimitive() || raw.isArray() || raw.isEnum() || raw.isInterface()
                || Modifier.isAbstract(raw.getModifiers())) {
            return false;
        }
        String name = raw.getName();
        return !(name.startsWith("java.") || name.startsWith("javax.") || name.startsWith("jdk.")
            || name.startsWith("sun.") || name.startsWith("com.fasterxml.jackson."));
    }

    private static Map<String, JavaType> readProperties(JavaType type) {
        return READ_PROPERTIES.computeIfAbsent(type, key -> {
            Map<String, JavaType> properties = new LinkedHashMap<>();
            for (BeanPropertyDefinition property : MAPPER.getDeserializationConfig().introspect(key).findProperties()) {
                properties.put(property.getName(), property.getPrimaryType());
            }
            return Collections.unmodifiableMap(properties);
        });
    }

    private static Map<String, AnnotatedMember> writeProperties(Class<?> type) {
        return WRITE_PROPERTIES.computeIfAbsent(type, key -> {
            Map<String, AnnotatedMember> properties = new LinkedHashMap<>();
            BeanDescription description = MAPPER.getSerializationConfig().introspect(javaType(key));
            for (BeanPropertyDefinition property : description.findProperties()) {
                AnnotatedMember accessor = property.getAccessor();
                if (accessor != null) {
                    accessor.fixAccess(true);
                    properties.put(property.getName(), accessor);
                }
            }
            return Collections.unmodifiableMap(properties);
        });
    }

    // Writing

    /**
     * {@code value} as JSON text, checked as it's written.
     *
     * @throws PayloadException if it isn't made of payload types, has an integer out of range, a
     *                          NaN or an infinity, or refers back to itself
     */
    public static String toJson(Object value) {
        JsonNode tree = write(value, "payload", Collections.newSetFromMap(new IdentityHashMap<>()));
        try {
            return MAPPER.writeValueAsString(tree);
        } catch (JsonProcessingException e) {
            throw new PayloadException("payload can't be written: " + e.getOriginalMessage());
        }
    }

    private static JsonNode write(Object value, String path, Set<Object> open) {
        if (value == null) {
            return NODES.nullNode();
        }
        if (value instanceof Boolean b) {
            return NODES.booleanNode(b);
        }
        if (value instanceof String s) {
            return NODES.textNode(s);
        }
        if (value instanceof Integer i) {
            return NODES.numberNode(i);
        }
        if (value instanceof Long l) {
            if (Math.abs(l) > MAX_INTEGER) {
                throw new PayloadException(path + " is " + l + ", past ±(2^53 − 1)");
            }
            return NODES.numberNode(l);
        }
        if (value instanceof Double d) {
            return NODES.numberNode(finite(d, path));
        }
        if (value instanceof Float f) {
            return NODES.numberNode((float) finite(f, path));
        }
        Class<?> type = value.getClass();
        boolean container = (type.isArray() && type != byte[].class) || value instanceof List<?>
            || value instanceof Map<?, ?>;
        if (!container && !isRecord(type)) {
            throw new PayloadException(path + " is " + type.getSimpleName() + ", not an AnyCall payload type");
        }
        if (!open.add(value)) {
            throw new PayloadException(path + " refers back to an object that contains it; a payload is a tree");
        }
        try {
            if (type.isArray()) {
                ArrayNode array = NODES.arrayNode();
                for (int i = 0; i < Array.getLength(value); i++) {
                    array.add(write(Array.get(value, i), path + "[" + i + "]", open));
                }
                return array;
            }
            if (value instanceof List<?> list) {
                ArrayNode array = NODES.arrayNode();
                int i = 0;
                for (Object item : list) {
                    array.add(write(item, path + "[" + i++ + "]", open));
                }
                return array;
            }
            if (value instanceof Map<?, ?> map) {
                ObjectNode object = NODES.objectNode();
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    if (!(entry.getKey() instanceof String key)) {
                        throw new PayloadException(path + " has the key " + entry.getKey() + "; map keys are Strings");
                    }
                    object.set(key, write(entry.getValue(), path + "[\"" + key + "\"]", open));
                }
                return object;
            }
            ObjectNode object = NODES.objectNode();
            Map<String, AnnotatedMember> properties;
            try {
                properties = writeProperties(type);
            } catch (RuntimeException e) {
                throw new PayloadException(path + " is " + type.getName() + ", which can't be read: " + e.getMessage());
            }
            for (Map.Entry<String, AnnotatedMember> property : properties.entrySet()) {
                String field = type.getSimpleName() + "." + property.getKey();
                Object fieldValue;
                try {
                    fieldValue = property.getValue().getValue(value);
                } catch (RuntimeException e) {
                    throw new PayloadException(field + " can't be read: " + e.getMessage());
                }
                object.set(property.getKey(), write(fieldValue, field, open));
            }
            return object;
        } finally {
            open.remove(value);
        }
    }

    private static double finite(double value, String path) {
        if (!Double.isFinite(value)) {
            throw new PayloadException(path + " is " + value + "; JSON has no NaN or infinity");
        }
        return value;
    }

    // Reading

    /**
     * JSON text read into {@code type}, a checked payload type. A whole payload of {@code null}
     * is null whatever the type, as the protocol has a method that returns null send it.
     *
     * @throws PayloadException if it isn't JSON, or doesn't fit {@code type}
     */
    public static Object fromJson(String json, JavaType type) {
        JsonNode tree;
        try {
            tree = MAPPER.readTree(json);
        } catch (JsonProcessingException e) {
            throw new PayloadException("payload isn't JSON: " + e.getOriginalMessage());
        }
        if (tree == null || tree.isNull()) {
            if (type.isPrimitive()) {
                throw new PayloadException("payload should be " + type.toCanonical() + ", got null");
            }
            return null;
        }
        read(tree, type, "payload");
        try {
            return MAPPER.treeToValue(tree, type);
        } catch (JsonProcessingException | IllegalArgumentException e) {
            throw new PayloadException("payload doesn't fit " + type.toCanonical() + ": " + e.getMessage());
        }
    }

    /** Checks {@code node} fits {@code type} by the payload rules, before Jackson reads it. */
    private static void read(JsonNode node, JavaType type, String path) {
        Class<?> raw = type.getRawClass();
        if (node.isNull()) {
            if (type.isPrimitive()) {
                throw mismatch(path, type, node);
            }
            return;
        }
        if (raw == boolean.class || raw == Boolean.class) {
            require(node.isBoolean(), path, type, node);
        } else if (raw == int.class || raw == Integer.class || raw == long.class || raw == Long.class) {
            require(node.isIntegralNumber(), path, type, node);
            if (!node.canConvertToLong() || Math.abs(node.longValue()) > MAX_INTEGER) {
                throw new PayloadException(path + " is " + node.asText() + ", past ±(2^53 − 1)");
            }
            if ((raw == int.class || raw == Integer.class) && !node.canConvertToInt()) {
                throw new PayloadException(path + " is " + node.asText() + ", past what an int holds");
            }
        } else if (raw == float.class || raw == Float.class || raw == double.class || raw == Double.class) {
            require(node.isNumber(), path, type, node);
        } else if (raw == String.class) {
            require(node.isTextual(), path, type, node);
        } else if (type.isArrayType() || type.isCollectionLikeType()) {
            require(node.isArray(), path, type, node);
            for (int i = 0; i < node.size(); i++) {
                read(node.get(i), type.getContentType(), path + "[" + i + "]");
            }
        } else if (type.isMapLikeType()) {
            require(node.isObject(), path, type, node);
            for (Iterator<Map.Entry<String, JsonNode>> it = node.fields(); it.hasNext(); ) {
                Map.Entry<String, JsonNode> field = it.next();
                read(field.getValue(), type.getContentType(), path + "[\"" + field.getKey() + "\"]");
            }
        } else {
            require(node.isObject(), path, type, node);
            readRecord(node, type);
        }
    }

    private static void readRecord(JsonNode node, JavaType type) {
        String name = type.getRawClass().getSimpleName();
        Map<String, JavaType> properties = readProperties(type);
        Set<String> unknown = new TreeSet<>();
        node.fieldNames().forEachRemaining(field -> {
            if (!properties.containsKey(field)) {
                unknown.add(field);
            }
        });
        if (!unknown.isEmpty()) {
            throw new PayloadException(name + " has no field " + String.join(", ", unknown));
        }
        List<String> missing = new ArrayList<>();
        for (String property : properties.keySet()) {
            if (!node.has(property)) {
                missing.add(property);
            }
        }
        if (!missing.isEmpty()) {
            throw new PayloadException(name + " is missing " + String.join(", ", missing));
        }
        properties.forEach((property, propertyType) -> read(node.get(property), propertyType, name + "." + property));
    }

    private static void require(boolean fits, String path, JavaType type, JsonNode node) {
        if (!fits) {
            throw mismatch(path, type, node);
        }
    }

    private static PayloadException mismatch(String path, JavaType type, JsonNode node) {
        String got = switch (node.getNodeType()) {
            case NULL -> "null";
            case BOOLEAN -> "a boolean";
            case NUMBER -> "a number";
            case STRING -> "a string";
            case ARRAY -> "an array";
            default -> "an object";
        };
        return new PayloadException(path + " should be " + type.getRawClass().getSimpleName() + ", got " + got);
    }
}
