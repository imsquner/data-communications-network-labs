#include <algorithm>
#include <array>
#include <bitset>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <initializer_list>
#include <iostream>
#include <numeric>
#include <random>
#include <stdexcept>
#include <vector>

using Byte = std::uint8_t;
using Word = std::uint16_t;

constexpr unsigned payloadSize = 8;
constexpr unsigned trials = 10000;
constexpr unsigned seed = 20261119;
constexpr unsigned hammingWidth = 11;
constexpr std::array<unsigned, 7> dataPositions{3, 5, 6, 7, 9, 10, 11};
using Frame = std::array<Byte, payloadSize + 2>;

Word crc16(const Byte* data, unsigned size) {
    Word reg = 0xFFFF;
    for (unsigned i = 0; i < size; ++i) {
        reg ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            reg = static_cast<Word>((reg >> 1) ^ ((reg & 1) ? 0xA001 : 0));
        }
    }
    return reg;
}

bool crcValid(const Byte* frame, unsigned size) {
    if (size < 2) return false;
    const auto received = static_cast<Word>(frame[size - 2] | (frame[size - 1] << 8));
    return crc16(frame, size - 2) == received;
}

void fillRandom(Byte* data, unsigned size, unsigned low, unsigned high, std::mt19937& rng) {
    std::uniform_int_distribution<unsigned> draw(low, high);
    for (unsigned i = 0; i < size; ++i) data[i] = static_cast<Byte>(draw(rng));
}

Frame makeFrame(std::mt19937& rng) {
    Frame frame{};
    fillRandom(frame.data(), payloadSize, 0, 255, rng);
    const Word crc = crc16(frame.data(), payloadSize);
    frame[payloadSize] = static_cast<Byte>(crc);
    frame[payloadSize + 1] = static_cast<Byte>(crc >> 8);
    return frame;
}

std::vector<unsigned> errorPositions(unsigned width, unsigned count, std::mt19937& rng) {
    std::vector<unsigned> positions(width);
    std::iota(positions.begin(), positions.end(), 0u);
    for (unsigned i = 0; i < count; ++i) {
        std::uniform_int_distribution<unsigned> draw(i, width - 1);
        std::swap(positions[i], positions[draw(rng)]);
    }
    positions.resize(count);
    std::sort(positions.begin(), positions.end());
    return positions;
}

void flipFrame(Byte* frame, const std::vector<unsigned>& positions) {
    for (unsigned p : positions) frame[p / 8] ^= static_cast<Byte>(1u << (p % 8));
}

Word bitMask(unsigned position) {
    return static_cast<Word>(1u << (position - 1));
}

unsigned syndrome(Word word) {
    unsigned result = 0;
    for (unsigned p = 1; p <= hammingWidth; ++p) {
        if (word & bitMask(p)) result ^= p;
    }
    return result;
}

Word encode(Byte ascii) {
    Word word = 0;
    for (unsigned bit = 0; bit < dataPositions.size(); ++bit) {
        if ((ascii >> bit) & 1) word |= bitMask(dataPositions[bit]);
    }
    const unsigned parityMask = syndrome(word);
    for (unsigned p : {1u, 2u, 4u, 8u}) {
        if (parityMask & p) word |= bitMask(p);
    }
    return word;
}

Byte decode(Word word) {
    Byte ascii = 0;
    for (unsigned bit = 0; bit < dataPositions.size(); ++bit) {
        if (word & bitMask(dataPositions[bit])) ascii |= static_cast<Byte>(1u << bit);
    }
    return ascii;
}

void flipWord(Word& word, const std::vector<unsigned>& positions) {
    for (unsigned p : positions) word ^= bitMask(p + 1);
}

bool correct(Word& word, int* errorLocations) {
    std::fill_n(errorLocations, hammingWidth, -1);
    const unsigned p = syndrome(word);
    if (p == 0) return true;
    if (p <= hammingWidth) {
        errorLocations[0] = static_cast<int>(p - 1);
        word ^= bitMask(p);
    }
    return false;
}

enum Category { Clean, Detected, Undetected, Corrected, Miscorrected, Rejected };
constexpr std::array<const char*, 6> names{
    "clean", "detected", "undetected", "corrected", "miscorrected", "rejected"
};

Category hammingResult(bool errorFree, int candidate, Word result, Word original) {
    if (errorFree) return result == original ? Clean : Undetected;
    if (candidate < 0) return Rejected;
    return result == original ? Corrected : Miscorrected;
}

void require(bool pass, const char* message) {
    if (!pass) throw std::runtime_error(message);
}

void selfCheck() {
    constexpr Byte check[]{'1','2','3','4','5','6','7','8','9'};
    require(crc16(check, 9) == 0x4B37, "CRC reference vector mismatch");
    std::cout << "CRC reference: 0x4B37 PASS\n";
    Frame frame{0x01,0x03,0x00,0x00,0x00,0x0A,0x15,0xCD,0x00,0x00};
    const Word crc = crc16(frame.data(), payloadSize);
    frame[payloadSize] = static_cast<Byte>(crc);
    frame[payloadSize + 1] = static_cast<Byte>(crc >> 8);
    require(crcValid(frame.data(), static_cast<unsigned>(frame.size())), "CRC clean frame failed");
    for (unsigned p = 0; p < frame.size() * 8; ++p) {
        Frame damaged = frame;
        flipFrame(damaged.data(), {p});
        require(!crcValid(damaged.data(), static_cast<unsigned>(damaged.size())), "CRC missed one bit");
    }
    std::cout << "CRC single-bit: 80/80 PASS\n";

    std::array<int, hammingWidth> locations{};
    for (unsigned value = 0; value < 128; ++value) {
        const Word original = encode(static_cast<Byte>(value));
        Word received = original;
        require(correct(received, locations.data()) && decode(received) == value, "Hamming clean check failed");
        for (unsigned p = 1; p <= hammingWidth; ++p) {
            received = static_cast<Word>(original ^ bitMask(p));
            require(!correct(received, locations.data()) && locations[0] == static_cast<int>(p - 1)
                && received == original && decode(received) == value, "Hamming single-bit check failed");
        }
    }
    std::cout << "Hamming clean: 128/128 PASS\nHamming single-bit: 1408/1408 PASS\n";
}

void printBytes(const Byte* data, unsigned size) {
    for (unsigned i = 0; i < size; ++i) {
        if (i != 0) std::cout << ' ';
        std::cout << std::hex << std::uppercase << std::setw(2) << std::setfill('0')
                  << static_cast<unsigned>(data[i]);
    }
    std::cout << std::dec << std::setfill(' ');
}

void printPositions(const std::vector<unsigned>& positions) {
    if (positions.empty()) std::cout << '-';
    for (unsigned i = 0; i < positions.size(); ++i) {
        if (i != 0) std::cout << ',';
        std::cout << positions[i];
    }
}

void demonstrations(std::mt19937& rng) {
    Byte sample{};
    fillRandom(&sample, 1, 0, 255, rng);
    Word crc = crc16(&sample, 1);
    const std::array<Byte,3> shortFrame{sample, static_cast<Byte>(crc), static_cast<Byte>(crc >> 8)};
    auto damaged = shortFrame;
    flipFrame(damaged.data(), {0});
    std::cout << "\nCRC hand-check frame: ";
    printBytes(shortFrame.data(), 3);
    std::cout << " | damaged: ";
    printBytes(damaged.data(), 3);
    std::cout << " | recalculated tail: ";
    crc = crc16(damaged.data(), 1);
    const std::array<Byte,2> newTail{static_cast<Byte>(crc), static_cast<Byte>(crc >> 8)};
    printBytes(newTail.data(), 2);
    std::cout << " | outcome=" << (crcValid(damaged.data(), 3) ? "ACCEPT" : "REJECT") << '\n';

    const Frame original = makeFrame(rng);
    constexpr unsigned frameSize = payloadSize + 2;
    std::cout << "\nCRC original data + CRC (low byte first): ";
    printBytes(original.data(), frameSize);
    std::cout << '\n';
    for (unsigned count = 0; count <= 10; ++count) {
        Frame received = original;
        const auto positions = errorPositions(frameSize * 8, count, rng);
        flipFrame(received.data(), positions);
        std::cout << "CRC k=" << count << " positions=";
        printPositions(positions);
        std::cout << " received=";
        printBytes(received.data(), frameSize);
        std::cout << " outcome=" << (crcValid(received.data(), frameSize) ? "ACCEPT" : "REJECT") << '\n';
    }

    std::array<Byte, 6> ascii{};
    fillRandom(ascii.data(), static_cast<unsigned>(ascii.size()), 32, 126, rng);
    std::cout << "\nASCII frame (decimal -> 11-bit codeword, position 11 to 1):\n";
    for (Byte value : ascii) {
        std::cout << static_cast<unsigned>(value) << " -> " << std::bitset<hammingWidth>(encode(value)) << '\n';
    }
    const Word word = encode(ascii.front());
    Word single = static_cast<Word>(word ^ bitMask(6));
    const Word incoming = single;
    std::array<int, hammingWidth> locations{};
    correct(single, locations.data());
    std::cout << "Hamming hand-check: original=" << std::bitset<hammingWidth>(word)
              << " flipped-index=5 received=" << std::bitset<hammingWidth>(incoming)
              << " syndrome=" << syndrome(incoming) << " candidate-index=" << locations[0]
              << " output-ASCII=" << static_cast<unsigned>(decode(single)) << '\n';

    for (unsigned count = 0; count <= hammingWidth; ++count) {
        Word received = word;
        const auto positions = errorPositions(hammingWidth, count, rng);
        flipWord(received, positions);
        std::cout << "Hamming k=" << count << " positions=";
        printPositions(positions);
        std::cout << " received=" << std::bitset<hammingWidth>(received) << " syndrome=" << syndrome(received);
        const bool errorFree = correct(received, locations.data());
        const auto result = hammingResult(errorFree, locations[0], received, word);
        std::cout << " candidate=" << locations[0] << " output=" << std::bitset<hammingWidth>(received)
                  << " output-ASCII=" << static_cast<unsigned>(decode(received))
                  << " outcome=" << names[result] << '\n';
    }
}

void statistics(std::mt19937& rng) {
    std::ofstream csv("statistics.csv");
    if (!csv) throw std::runtime_error("Cannot open statistics.csv");
    csv << "scheme,bits,trials,clean,detected,undetected,corrected,miscorrected,rejected\n";
    for (bool hamming : {false, true}) {
        const unsigned limit = hamming ? hammingWidth : 10;
        for (unsigned count = 0; count <= limit; ++count) {
            std::array<unsigned, names.size()> totals{};
            for (unsigned trial = 0; trial < trials; ++trial) {
                if (hamming) {
                    Byte ascii{};
                    fillRandom(&ascii, 1, 0, 127, rng);
                    const Word word = encode(ascii);
                    Word received = word;
                    flipWord(received, errorPositions(hammingWidth, count, rng));
                    std::array<int, hammingWidth> locations{};
                    const bool errorFree = correct(received, locations.data());
                    ++totals[hammingResult(errorFree, locations[0], received, word)];
                } else {
                    Frame received = makeFrame(rng);
                    const unsigned size = static_cast<unsigned>(received.size());
                    const Frame original = received;
                    const auto positions = errorPositions(size * 8, count, rng);
                    flipFrame(received.data(), positions);
                    if (crcValid(received.data(), size)) {
                        if (count > 0 && totals[Undetected] == 0) {
                            std::cout << "CRC undetected example k=" << count << " positions=";
                            printPositions(positions);
                            std::cout << " original=";
                            printBytes(original.data(), size);
                            std::cout << " received=";
                            printBytes(received.data(), size);
                            std::cout << '\n';
                        }
                        ++totals[count == 0 ? Clean : Undetected];
                    } else {
                        ++totals[Detected];
                    }
                }
            }
            csv << (hamming ? "Hamming" : "CRC") << ',' << count << ',' << trials;
            for (unsigned total : totals) csv << ',' << total;
            csv << '\n';
        }
    }
    csv.close();
    if (!csv) throw std::runtime_error("Cannot write statistics.csv");
    std::cout << "\nStatistics: 23 groups x 10000 trials = 230000\n";
}

int main() {
    try {
        std::cout << "NetLab 1: CRC-16/Modbus and Hamming(11,7)\n"
                  << "Seed: " << seed << " | positions are zero-based\n";
        selfCheck();
        std::mt19937 rng(seed);
        demonstrations(rng);
        statistics(rng);
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}

