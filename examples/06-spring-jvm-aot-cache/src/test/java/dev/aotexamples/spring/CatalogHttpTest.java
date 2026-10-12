package dev.aotexamples.spring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class CatalogHttpTest {
    @Value("${local.server.port}")
    private int port;
    private final HttpClient client = HttpClient.newHttpClient();

    private HttpResponse<String> request(String path, String body) throws Exception {
        var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).timeout(Duration.ofSeconds(5));
        if (body != null) {
            builder.header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body));
        }
        return client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }

    @Test
    void reportsReadyAfterApplicationStartup() throws Exception {
        var response = request("/ready", null);
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("\"ready\":true"));
        assertTrue(response.body().contains("\"productCount\":8"));
    }

    @Test
    void returnsProductAndNotFound() throws Exception {
        assertEquals("{\"id\":1,\"name\":\"Keyboard\",\"priceCents\":9900}", request("/products/1", null).body());
        assertEquals(404, request("/products/99", null).statusCode());
    }

    @Test
    void calculatesQuoteFromJson() throws Exception {
        var response = request("/quotes", "{\"quantities\":{\"1\":2,\"2\":1}}");
        assertEquals(200, response.statusCode());
        assertEquals("{\"subtotalCents\":22300,\"discountCents\":2230,\"totalCents\":20070}", response.body());
    }

    @Test
    void rejectsInvalidAndMalformedOrders() throws Exception {
        for (String body : new String[] {"{}", "{\"quantities\":{}}", "{\"quantities\":{\"1\":0}}",
                "{\"quantities\":{\"99\":1}}", "{\"quantities\":{\"1\":null}}", "not-json"}) {
            assertEquals(400, request("/quotes", body).statusCode(), body);
        }
    }

    @Test
    void computesChecksumAndRejectsUnboundedWork() throws Exception {
        var response = request("/compute?iterations=100000", null);
        assertEquals(200, response.statusCode());
        assertEquals("{\"iterations\":100000,\"checksum\":-7520082499104634107}", response.body());
        for (String iterations : new String[] {"0", "10000001", "nope"}) {
            assertEquals(400, request("/compute?iterations=" + iterations, null).statusCode());
        }
    }
}
