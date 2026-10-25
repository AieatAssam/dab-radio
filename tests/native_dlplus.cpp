#include "pad_decoder.h"
#include <cassert>
#include <iostream>

static std::vector<uint8_t> crc(std::vector<uint8_t> bytes) {
    auto value = CalcCRC::CalcCRC_CRC16_CCITT.Calc(bytes.data(), bytes.size());
    bytes.push_back(value >> 8); bytes.push_back(value & 255); return bytes;
}
static void label(DynamicLabelDecoder& decoder, const std::string& text, uint8_t charset = 0) {
    assert(text.size() <= 16);
    std::vector<uint8_t> data = {static_cast<uint8_t>(0x60 | (text.size() - 1)), static_cast<uint8_t>(charset << 4)};
    data.insert(data.end(), text.begin(), text.end()); data = crc(data);
    assert(decoder.ProcessDataSubfield(true, data.data(), data.size()));
}
int main() {
    DynamicLabelDecoder decoder;
    label(decoder, "Song - Artist");
    auto tags = crc({0x72, 0x06, 0x05, 1, 0, 3, 4, 7, 5});
    assert(decoder.ProcessDataSubfield(true, tags.data(), tags.size()));
    auto result = decoder.GetLabel();
    assert(result.dl_plus_ir && result.dl_plus_objects.size() == 2);
    assert(result.dl_plus_objects[0].text == "Song");
    assert(result.dl_plus_objects[1].text == "Artist");
    decoder.Reset(); label(decoder, u8"Café - Björk", 15);
    tags = crc({0x72, 0x06, 0x05, 1, 0, 3, 4, 7, 4});
    assert(decoder.ProcessDataSubfield(true, tags.data(), tags.size()));
    result = decoder.GetLabel();
    assert(result.dl_plus_objects[0].text == u8"Café");
    assert(result.dl_plus_objects[1].text == u8"Björk");
    decoder.Reset(); label(decoder, "Song - Artist");
    auto broken = tags; broken.back() ^= 1;
    assert(!decoder.ProcessDataSubfield(true, broken.data(), broken.size()));
    assert(decoder.GetLabel().dl_plus_objects.empty());
    auto truncated = crc({0x72, 0x00, 0x07});
    decoder.ProcessDataSubfield(true, truncated.data(), truncated.size());
    assert(decoder.GetLabel().dl_plus_objects.empty());
    auto remove = crc({0x71, 0x00});
    assert(decoder.ProcessDataSubfield(true, remove.data(), remove.size()));
    assert(decoder.GetLabel().raw.empty());
    std::cout << "Native DL+ CRC, typed tags, Unicode, truncation, and label removal passed\n";
}
