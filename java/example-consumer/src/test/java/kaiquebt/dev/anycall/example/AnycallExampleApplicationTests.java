package kaiquebt.dev.anycall.example;

import org.junit.Test;

public class AnycallExampleApplicationTests {

	@Test
	public void testBasic() {
		CreateProductRequest request = new CreateProductRequest("test", 123);
		assert request.name().equals("test");
		assert request.priceInCents() == 123;
	}

}
