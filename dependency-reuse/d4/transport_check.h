#ifndef DEAGLE_TRANSPORT_CHECK_H
#define DEAGLE_TRANSPORT_CHECK_H
#include <stdexcept>
namespace d42 {
inline void need(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
}
#endif
