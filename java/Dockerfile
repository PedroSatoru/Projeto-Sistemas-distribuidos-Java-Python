FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build

COPY pom.xml .
COPY src ./src
RUN mvn -Dmaven.test.skip=true clean package

FROM eclipse-temurin:21-jre
WORKDIR /app

COPY --from=build /build/target/chat-app.jar /app/app.jar
COPY users.txt /app/users.txt
RUN mkdir -p /data

ENTRYPOINT ["java", "-cp", "/app/app.jar"]
